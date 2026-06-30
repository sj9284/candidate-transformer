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

# Contact info confidence
CONTACT_BASE_SCORE = 0.85
CONTACT_MULTIPLIER = 0.15

# Experience scoring weights
EXPERIENCE_WEIGHTS = {
    "base": 0.5,
    "company": 0.2,
    "title": 0.15,
    "dates": 0.15
}

# Education scoring weights
EDUCATION_WEIGHTS = {
    "base": 0.5,
    "institution": 0.2,
    "degree": 0.2,
    "end_year": 0.1
}

# Skills
MAX_SKILL_VOLUME_BONUS = 0.05

# Overall weighted average prioritizations
OVERALL_FIELD_WEIGHTS = [1.5, 1.5, 2.0, 1.0, 1.0] # Email, Phone, Exp, Edu, Skills


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
# Per-skill confidence
# ---------------------------------------------------------------------------

def compute_skill_confidence(skill_name: str, sources: list[str]) -> float:
    """
    Compute the confidence score for one skill.
    """
    unique_sources = list(dict.fromkeys(sources))
    if not unique_sources:
        return 0.0

    base = _skill_base_score(len(unique_sources))
    weight = _avg([_weight(s) for s in unique_sources])
    confidence = base * weight

    logger.debug(
        "skill_confidence: skill=%r sources=%s result=%.4f",
        skill_name, unique_sources, confidence,
    )
    return round(confidence, 4)


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
    # Determine source list
    sources = merged.get("_merged_sources") or []

    # Convert flat skill name list → enriched skill dicts
    skill_names = merged.get("skills", [])
    skill_sources = merged.get("_skills_sources", {})
    if skill_names and isinstance(skill_names[0], str):
        merged["skills"] = enrich_skills_with_confidence(skill_names, sources, skill_sources)

    # Calculate overall confidence dynamically based on data completeness
    field_scores = []
    
    # 1. Email confidence
    if merged.get("emails"):
        email_score = min(1.0, CONTACT_BASE_SCORE + (len(merged["emails"]) - 1) * CONTACT_MULTIPLIER)
        field_scores.append(email_score)
    else:
        field_scores.append(0.0)
        
    # 2. Phone confidence
    if merged.get("phones"):
        phone_score = min(1.0, CONTACT_BASE_SCORE + (len(merged["phones"]) - 1) * CONTACT_MULTIPLIER)
        field_scores.append(phone_score)
    else:
        field_scores.append(0.0)
        
    # 3. Experience confidence (based on completeness of entries)
    exp_list = merged.get("experience", [])
    if exp_list:
        entry_scores = []
        for exp in exp_list:
            score = EXPERIENCE_WEIGHTS["base"]
            if exp.get("company"): score += EXPERIENCE_WEIGHTS["company"]
            if exp.get("title"): score += EXPERIENCE_WEIGHTS["title"]
            if exp.get("start") and exp.get("end"): score += EXPERIENCE_WEIGHTS["dates"]
            entry_scores.append(score)
        avg_exp = sum(entry_scores) / len(entry_scores)
        field_scores.append(avg_exp)
    else:
        field_scores.append(0.3)
        
    # 4. Education confidence (based on completeness of entries)
    edu_list = merged.get("education", [])
    if edu_list:
        entry_scores = []
        for edu in edu_list:
            score = EDUCATION_WEIGHTS["base"]
            if edu.get("institution"): score += EDUCATION_WEIGHTS["institution"]
            if edu.get("degree"): score += EDUCATION_WEIGHTS["degree"]
            if edu.get("end_year"): score += EDUCATION_WEIGHTS["end_year"]
            entry_scores.append(score)
        avg_edu = sum(entry_scores) / len(entry_scores)
        field_scores.append(avg_edu)
    else:
        field_scores.append(0.3)
        
    # 5. Skills confidence (based on volume and average skill confidence)
    if merged.get("skills"):
        skill_count = len(merged["skills"])
        avg_skill = sum(s.get("confidence", 0.82) for s in merged["skills"]) / skill_count
        volume_boost = min(MAX_SKILL_VOLUME_BONUS, (skill_count / 10) * MAX_SKILL_VOLUME_BONUS)
        field_scores.append(min(1.0, avg_skill + volume_boost))
    else:
        field_scores.append(0.3)

    # Set overall_confidence (weighted average prioritizing contact info and experience)
    weighted_sum = sum(s * w for s, w in zip(field_scores, OVERALL_FIELD_WEIGHTS))
    merged["overall_confidence"] = round(weighted_sum / sum(OVERALL_FIELD_WEIGHTS), 4)

    # Enrich provenance entries with confidence
    provenance = merged.get("_provenance", [])
    for p in provenance:
        if p["field"] == "skills":
            # Lookup specific skill confidence
            val = p.get("value")
            skill_conf = next((s["confidence"] for s in merged.get("skills", []) if s.get("name") == val), None)
            if skill_conf is not None:
                p["confidence"] = skill_conf
            else:
                p["confidence"] = compute_skill_confidence(str(val), [p["source"]])
        else:
            # Use source-specific base confidence for other fields
            src = p.get("source", "")
            if src == "none":
                p["confidence"] = 0.0
            else:
                p["confidence"] = _weight(src)

    logger.info(
        "Confidence scored: name=%r overall=%.4f skills=%d sources=%s",
        merged.get("full_name"), merged["overall_confidence"],
        len(merged.get("skills", [])), sources,
    )

    return merged
