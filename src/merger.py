"""
Phase 7 — Merge Engine
=======================
Combines a cluster of validated dicts (same person, multiple sources)
into a single merged candidate dict ready for the confidence engine and
canonical profile builder.

Design rules:
- Per-field conflict policy is a literal lookup table (see FIELD_POLICY).
  No single global rule — each field has an explicit reason.
- List fields are unioned and deduplicated, never overwritten.
- Every conflict resolved is logged: field, sources that disagreed,
  winning source, and the policy that decided it.
- Provenance entries are generated here and carried forward to Phase 10.
- Output dict is flat (no Pydantic yet) so Phase 8 and 9 can inspect it
  before Phase 10 instantiates the canonical model.

Per-field conflict policy table
(also reproduced in README — both must stay in sync):

  Field              Preferred source   Rationale
  ─────────────────  ────────────────   ──────────────────────────────────────
  emails             union all          list field — keep all, deduplicate
  phones             union all          list field — keep all, deduplicate
  skills             union all          list field — union + deduplicate names
  full_name          csv > resume       recruiter-verified spelling
  location           csv > resume       structured, rarely conflicts
  headline           resume > csv       usually absent from CSV
  years_experience   resume > csv       resume has richer date context
  experience         resume > csv       richer unstructured detail
  education          resume > csv       richer unstructured detail
  links.*            first non-null     different sources have different links
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source type classification
# ---------------------------------------------------------------------------

def _source_type(source: str) -> str:
    """Return 'structured' for CSV, 'unstructured' for PDF/text, else 'other'."""
    src = source.lower()
    if src.endswith(".csv"):
        return "structured"
    if src.endswith((".pdf", ".docx", ".txt")):
        return "unstructured"
    return "other"


def _is_csv(d: dict) -> bool:
    return _source_type(d.get("_source", "")) == "structured"


def _is_resume(d: dict) -> bool:
    return _source_type(d.get("_source", "")) == "unstructured"


# ---------------------------------------------------------------------------
# Per-field policy table
# ---------------------------------------------------------------------------

# Scalar field preference: "csv" means CSV wins when both have values,
# "resume" means resume wins. "first_non_null" picks whatever appears first.
FIELD_POLICY: dict[str, str] = {
    "full_name":        "csv",
    "location_city":    "csv",
    "location_region":  "csv",
    "location_country": "csv",
    "headline":         "resume",
    "years_experience": "resume",
}

# List fields are always unioned — never in FIELD_POLICY.
LIST_FIELDS = {"emails", "phones", "skills"}

# Experience / education blocks: always prefer the resume source.
BLOCK_FIELDS = {"experience", "education"}

# Link sub-fields: first non-null across all sources wins.
LINK_FIELDS = {"linkedin", "github", "portfolio"}


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def _prov(field: str, value: Any, source: str, method: str) -> dict[str, Any]:
    return {"field": field, "value": value, "source": source, "method": method}


def _method_for_source(source: str) -> str:
    """Return the base provenance method string for a given source."""
    return "csv_direct" if _is_csv({"_source": source}) else "regex_extract"


# ---------------------------------------------------------------------------
# List-field merger
# ---------------------------------------------------------------------------

def _merge_list_field(
    field: str, dicts: list[dict], provenance: list[dict]
) -> tuple[list, dict[str, list[str]]]:
    """
    Merge list fields across dicts, preserving order and removing duplicates.
    Case-insensitive deduplication for strings.

    Returns:
        (merged_list, dict mapping each value to a list of source filenames)
    """
    seen: set[str] = set()
    result: list = []
    
    # Mapping of value -> list of sources that provided it
    val_to_sources: dict[str, list[str]] = {}

    for d in dicts:
        values = d.get(field, []) or []
        if not isinstance(values, list):
            values = [values]
        src = d.get("_source", "unknown")
        for v in values:
            if v is None:
                continue
            key = str(v).lower() if isinstance(v, str) else str(v)
            val_to_sources.setdefault(v, []).append(src)
            
            if key not in seen:
                seen.add(key)
                result.append(v)
                
    if field == "phones":
        unique_phones = []
        seen_10 = set()
        # Prefer +91 if there's a collision
        for v in sorted(result, key=lambda x: not str(x).startswith("+91")):
            last_10 = str(v)[-10:]
            if last_10 not in seen_10:
                seen_10.add(last_10)
                unique_phones.append(v)
        result = unique_phones
                
    if result:
        # Generate provenance for each unique value, citing all sources
        for v in result:
            sources = val_to_sources[v]
            # Log the primary source (the first one) in the official provenance entry
            # The full list is used later for confidence scoring
            primary_src = sources[0]
            method = "resume_keyword" if _source_type(primary_src) == "unstructured" else _method_for_source(primary_src)
            provenance.append(_prov(field, v, primary_src, method))

    return result, val_to_sources


# ---------------------------------------------------------------------------
# Scalar-field merger
# ---------------------------------------------------------------------------

def _merge_scalar_field(
    field: str,
    dicts: list[dict],
    provenance: list[dict],
) -> Any:
    """
    Merge a scalar field according to the FIELD_POLICY table.

    Steps:
      1. Collect all non-null values grouped by source type.
      2. If only one unique value → no conflict, pick it.
      3. If multiple unique values → apply policy, log the conflict.
    """
    policy = FIELD_POLICY.get(field, "csv")   # default to csv preference

    # Collect (value, source) pairs where value is not None
    candidates: list[tuple[Any, str]] = [
        (d[field], d.get("_source", "unknown"))
        for d in dicts
        if d.get(field) is not None
    ]

    if not candidates:
        provenance.append(_prov(field, None, "none", "default"))
        return None

    # Deduplicate values (keep first occurrence per unique value)
    unique_values = list(dict.fromkeys(v for v, _ in candidates))

    if len(unique_values) == 1:
        # No conflict — all sources agree
        source = candidates[0][1]
        provenance.append(_prov(field, unique_values[0], source, _method_for_source(source)))
        return unique_values[0]

    # Conflict — multiple distinct values
    csv_candidates    = [(v, s) for v, s in candidates if _is_csv({"_source": s})]
    resume_candidates = [(v, s) for v, s in candidates if _is_resume({"_source": s})]

    if policy == "csv" and csv_candidates:
        winner_val, winner_src = csv_candidates[0]
        method = "merge_conflict_csv_won"
        losers = [s for _, s in candidates if s != winner_src]
    elif policy == "resume" and resume_candidates:
        winner_val, winner_src = resume_candidates[0]
        method = "merge_conflict_resume_won"
        losers = [s for _, s in candidates if s != winner_src]
    else:
        # Policy preference not available — fall back to first non-null
        winner_val, winner_src = candidates[0]
        method = "merge_conflict_csv_won" if _is_csv({"_source": winner_src}) else "merge_conflict_resume_won"
        losers = [s for _, s in candidates[1:]]

    logger.info(
        "Conflict on field=%r: winner=%r (source=%r, policy=%s) losers=%s",
        field, winner_val, winner_src, policy, losers,
    )
    provenance.append(_prov(field, winner_val, winner_src, method))
    return winner_val


# ---------------------------------------------------------------------------
# Block-field merger (experience / education)
# ---------------------------------------------------------------------------

def _merge_block_field(
    field: str,
    dicts: list[dict],
    provenance: list[dict],
) -> list[dict]:
    """
    For experience and education: prefer the resume source.
    If no resume source has data, fall back to CSV.
    """
    resume_vals = [
        (d.get(field, []), d.get("_source", "unknown"))
        for d in dicts if _is_resume(d) and d.get(field)
    ]
    csv_vals = [
        (d.get(field, []), d.get("_source", "unknown"))
        for d in dicts if _is_csv(d) and d.get(field)
    ]

    if resume_vals:
        val, src = resume_vals[0]
        method = "regex_extract" if len(resume_vals) + len(csv_vals) == 1 else "merge_conflict_resume_won"
        if csv_vals:
            logger.info("Conflict on field=%r: resume wins over csv (policy=resume)", field)
    elif csv_vals:
        val, src = csv_vals[0]
        method = "csv_direct"
    else:
        provenance.append(_prov(field, None, "none", "default"))
        return []

    provenance.append(_prov(field, None, src, method))
    return val if isinstance(val, list) else []


# ---------------------------------------------------------------------------
# Link-field merger
# ---------------------------------------------------------------------------

def _merge_links(
    dicts: list[dict],
    provenance: list[dict],
) -> dict[str, Any]:
    """
    Merge link sub-fields: first non-null value across all dicts wins.
    'other' links are unioned.
    """
    links: dict[str, Any] = {
        "linkedin":  None,
        "github":    None,
        "portfolio": None,
        "other":     [],
    }

    for field in ("linkedin", "github", "portfolio"):
        for d in dicts:
            val = d.get(field)
            if val and links[field] is None:
                links[field] = val
                src = d.get("_source", "unknown")
                provenance.append(_prov(f"links.{field}", val, src, _method_for_source(src)))
                break

    return links


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def merge_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge a cluster of validated dicts (same person) into one merged dict.

    Args:
        cluster: List of validated dicts from identity resolution.
                 Must be non-empty.

    Returns:
        A merged flat dict with:
          - All merged field values
          - "_merged_sources": list of all source filenames in this cluster
          - "_provenance":     list of provenance entry dicts

    Never raises.
    """
    if not cluster:
        return {}

    if len(cluster) == 1:
        d = cluster[0]
        src = d.get("_source", "unknown")
        provenance: list[dict] = []

        # Single source — simple provenance for each present field
        for field in ("full_name", "location_city", "location_region",
                      "location_country", "headline", "years_experience"):
            if d.get(field) is not None:
                provenance.append(_prov(field, d.get(field), src, _method_for_source(src)))

        for field in ("emails", "phones"):
            if d.get(field):
                for v in (d.get(field) if isinstance(d.get(field), list) else [d.get(field)]):
                    provenance.append(_prov(field, v, src, _method_for_source(src)))
                    
        if d.get("skills"):
            for v in (d.get("skills") if isinstance(d.get("skills"), list) else [d.get("skills")]):
                method = "resume_keyword" if _source_type(src) == "unstructured" else _method_for_source(src)
                provenance.append(_prov("skills", v, src, method))

        for block in ("experience", "education"):
            if d.get(block):
                provenance.append(_prov(block, None, src, _method_for_source(src)))

        links = _merge_links([d], provenance)

        return {
            "full_name":        d.get("full_name"),
            "emails":           d.get("emails") or [],
            "phones":           d.get("phones") or [],
            "location_city":    d.get("location_city"),
            "location_region":  d.get("location_region"),
            "location_country": d.get("location_country"),
            "links":            links,
            "headline":         d.get("headline"),
            "years_experience": d.get("years_experience"),
            "skills":           d.get("skills") or [],
            "experience":       d.get("experience") or [],
            "education":        d.get("education") or [],
            "_merged_sources":  [src],
            "_provenance":      provenance,
        }

    provenance: list[dict] = []

    # --- List fields (union) ---
    merged_emails, _ = _merge_list_field("emails", cluster, provenance)
    merged_phones, _ = _merge_list_field("phones", cluster, provenance)
    merged_skills, skill_sources = _merge_list_field("skills", cluster, provenance)

    # --- Scalar fields (policy table) ---
    full_name        = _merge_scalar_field("full_name",        cluster, provenance)
    location_city    = _merge_scalar_field("location_city",    cluster, provenance)
    location_region  = _merge_scalar_field("location_region",  cluster, provenance)
    location_country = _merge_scalar_field("location_country", cluster, provenance)
    headline         = _merge_scalar_field("headline",         cluster, provenance)
    years_exp        = _merge_scalar_field("years_experience", cluster, provenance)

    # --- Block fields (resume > csv) ---
    merged_experience = _merge_block_field("experience", cluster, provenance)
    merged_education  = _merge_block_field("education",  cluster, provenance)

    # --- Links (first non-null per sub-field) ---
    links = _merge_links(cluster, provenance)

    sources = list(dict.fromkeys(d.get("_source", "unknown") for d in cluster))

    merged = {
        "full_name":        full_name,
        "emails":           merged_emails,
        "phones":           merged_phones,
        "location_city":    location_city,
        "location_region":  location_region,
        "location_country": location_country,
        "links":            links,
        "headline":         headline,
        "years_experience": years_exp,
        "skills":           merged_skills,
        "experience":       merged_experience,
        "education":        merged_education,
        "years_experience": years_exp,
        "_merged_sources":  sources,
        "_provenance":      provenance,
        "_skills_sources":  skill_sources,
    }

    logger.info(
        "Merged cluster of %d dicts: name=%r emails=%s skills=%d exp=%d",
        len(cluster), full_name, merged_emails,
        len(merged_skills), len(merged_experience),
    )

    return merged


def merge_all(clusters: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """
    Merge every cluster into a single merged dict.

    Args:
        clusters: Output from cluster_candidates().

    Returns:
        List of merged dicts, one per cluster.
    """
    return [merge_cluster(c) for c in clusters]
