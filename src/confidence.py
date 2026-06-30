"""
Phase 8 — Confidence Engine
============================
Computes confidence scores for a merged candidate dict.

Two levels of scoring:
  1. overall_confidence — attached to the CandidateProfile
  2. per-skill confidence — attached to each Skill object

Formula (overall):
    overall_confidence = BASE_SCORE[source_count] × avg(reliability_weights)

Formula (per-skill):
    skill_confidence =
        SKILL_BASE[sources_mentioning_this_skill] × avg(weights_of_those_sources)

Design rules:
- Weight tables are small, explicit, and readable — no ML, no over-engineering.
- Scores are clamped to [0.0, 1.0] after calculation.
- Functions are pure: same inputs → same outputs.
- Documented rationale for every constant below.

Source reliability weight rationale:
  structured (CSV) = 1.0
    Human-typed, recruiter-verified — lowest extraction error rate.
  unstructured (resume PDF) = 0.85
    Extracted by regex from free text — higher chance of misparse.
    15% penalty reflects realistic extraction accuracy for regex-based parsers.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constant tables
# ---------------------------------------------------------------------------

# Base score by number of distinct sources confirming this candidate.
# Rationale: more corroborating sources = more confidence in data completeness.
BASE_SCORE: dict[int, float] = {
    1: 0.70,
    2: 0.90,
}
BASE_SCORE_MAX = 0.98   # 3 or more sources

# Per-source reliability weights.
# Key = source type string as returned by _source_type().
SOURCE_WEIGHT: dict[str, float] = {
    "structured":   1.00,   # CSV — structured, recruiter-verified
    "unstructured": 0.85,   # PDF resume — regex-extracted, higher error rate
    "other":        0.80,   # Unknown source type — conservative default
}

# Per-skill base scores (same structure as overall, kept separate for clarity).
SKILL_BASE_SCORE: dict[int, float] = {
    1: 0.70,
    2: 0.90,
}
SKILL_BASE_SCORE_MAX = 0.95   # 3+ sources confirm this skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_type(source: str) -> str:
    """Classify a source file by its extension."""
    src = source.lower()
    if src.endswith(".csv"):
        return "structured"
    if src.endswith((".pdf", ".docx", ".txt")):
        return "unstructured"
    return "other"


def _weight(source: str) -> float:
    """Return the reliability weight for a given source filename."""
    return SOURCE_WEIGHT.get(_source_type(source), SOURCE_WEIGHT["other"])


def _base_score(n: int) -> float:
    """Return the base score for n distinct sources."""
    if n <= 0:
        return 0.0
    return BASE_SCORE.get(n, BASE_SCORE_MAX)


def _skill_base_score(n: int) -> float:
    """Return the per-skill base score for n sources mentioning it."""
    if n <= 0:
        return 0.0
    return SKILL_BASE_SCORE.get(n, SKILL_BASE_SCORE_MAX)


def _clamp(value: float) -> float:
    """Clamp a float to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def _avg(values: list[float]) -> float:
    """Average a non-empty list. Returns 0.0 for empty list."""
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Overall confidence
# ---------------------------------------------------------------------------

def compute_overall_confidence(merged_sources: list[str]) -> float:
    """
    Compute the overall_confidence score for a candidate.

    Args:
        merged_sources: List of source filenames that contributed to
                        this candidate (from merged_dict["_merged_sources"]).
                        Duplicates are collapsed before scoring.

    Returns:
        float in [0.0, 1.0].

    Examples:
        ["recruiter.csv"]                    → 0.70 × 1.00 = 0.70
        ["recruiter.csv", "resume.pdf"]      → 0.90 × avg(1.0, 0.85) = 0.8325
        ["a.csv", "b.csv", "resume.pdf"]     → 0.98 × avg(1.0, 1.0, 0.85) = 0.9408
    """
    unique_sources = list(dict.fromkeys(merged_sources))   # stable dedup
    n = len(unique_sources)

    if n == 0:
        logger.warning("compute_overall_confidence called with empty source list")
        return 0.0

    weights = [_weight(s) for s in unique_sources]
    score = _base_score(n) * _avg(weights)
    result = _clamp(round(score, 4))

    logger.debug(
        "overall_confidence: sources=%s base=%.2f avg_weight=%.4f result=%.4f",
        unique_sources, _base_score(n), _avg(weights), result,
    )

    return result


# ---------------------------------------------------------------------------
# Per-skill confidence
# ---------------------------------------------------------------------------

def compute_skill_confidence(skill_name: str, sources: list[str]) -> float:
    """
    Compute the confidence score for one skill.

    Args:
        skill_name: Canonical skill name (used only for logging).
        sources:    List of source filenames that mentioned this skill.
                    May contain duplicates — they are collapsed.

    Returns:
        float in [0.0, 1.0].

    Examples:
        skill="python", sources=["recruiter.csv"]
            → 0.70 × 1.0 = 0.70

        skill="python", sources=["recruiter.csv", "resume.pdf"]
            → 0.90 × avg(1.0, 0.85) = 0.8325

        skill="go", sources=["resume.pdf"]
            → 0.70 × 0.85 = 0.595
    """
    unique_sources = list(dict.fromkeys(sources))
    n = len(unique_sources)

    if n == 0:
        return 0.0

    weights = [_weight(s) for s in unique_sources]
    score = _skill_base_score(n) * _avg(weights)
    result = _clamp(round(score, 4))

    logger.debug(
        "skill_confidence: skill=%r sources=%s result=%.4f",
        skill_name, unique_sources, result,
    )

    return result


# ---------------------------------------------------------------------------
# Skill list enrichment
# ---------------------------------------------------------------------------

def enrich_skills_with_confidence(
    skill_names: list[str],
    merged_sources: list[str],
    per_skill_sources: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Convert a flat list of skill name strings into skill dicts with confidence.

    Args:
        skill_names:      Canonical skill names from the merged dict.
        merged_sources:   All sources that contributed to this candidate.
                          Used as the fallback source list per skill.
        per_skill_sources: Optional mapping of skill_name → list[source].
                           If not provided, all skills are attributed to
                           all merged_sources (conservative: assume any source
                           could have provided it).

    Returns:
        list of {"name": str, "confidence": float, "sources": list[str]}
    """
    result: list[dict[str, Any]] = []

    for name in skill_names:
        if per_skill_sources and name in per_skill_sources:
            sources = per_skill_sources[name]
        else:
            sources = merged_sources

        confidence = compute_skill_confidence(name, sources)
        result.append({
            "name":       name,
            "confidence": confidence,
            "sources":    list(dict.fromkeys(sources)),   # deduplicated
        })

    return result


# ---------------------------------------------------------------------------
# Convenience: score a whole merged dict in one call
# ---------------------------------------------------------------------------

def score_merged_dict(merged: dict[str, Any]) -> dict[str, Any]:
    """
    Attach confidence scores to a merged dict in-place (returns same dict).

    Sets:
        merged["overall_confidence"] = float
        merged["skills"]             = list[dict] with confidence + sources

    Args:
        merged: Output from merger.merge_cluster().

    Returns:
        The same dict with confidence fields populated.
    """
    sources = merged.get("_merged_sources", [])

    merged["overall_confidence"] = compute_overall_confidence(sources)

    # Convert flat skill name list → enriched skill dicts
    skill_names = merged.get("skills", [])
    if skill_names and isinstance(skill_names[0], str):
        merged["skills"] = enrich_skills_with_confidence(skill_names, sources)
    # If already enriched (list of dicts), leave as-is.

    logger.info(
        "Confidence scored: name=%r overall=%.4f skills=%d sources=%s",
        merged.get("full_name"), merged["overall_confidence"],
        len(merged.get("skills", [])), sources,
    )

    return merged
