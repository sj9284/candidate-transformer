"""
Phase 10 — Build Canonical Profile
=====================================
Assembles a scored, merged dict into a fully validated CandidateProfile.

This is the single assembly point where everything comes together:
  merge engine output  →  confidence scores  →  provenance entries
  →  CandidateProfile(**data)  →  Pydantic validates  →  canonical truth

Design rules:
- CandidateProfile is the only object downstream stages ever touch.
  Nothing reads from raw/merged dicts after this point.
- On Pydantic ValidationError: log field + candidate identifier, return
  None for that record. Pipeline continues with remaining candidates.
- candidate_id is generated here using generate_candidate_id() from
  canonical_schema.py — deterministic sha256[:16] formula.
- Every sub-model (Location, Links, Skill, Experience, Education) is
  built through a dedicated coerce function so bad values are caught
  and defaulted rather than crashing the build.
"""

import logging
from typing import Any

from src.canonical_schema import (
    CandidateProfile,
    Education,
    Experience,
    Links,
    Location,
    Skill,
    generate_candidate_id,
)
from src.provenance import build_provenance_list, deduplicate_provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-model coercers — each returns a valid sub-model or a safe default
# ---------------------------------------------------------------------------

def _build_location(merged: dict[str, Any]) -> Location:
    """Build a Location from flat merged dict keys."""
    try:
        return Location(
            city    = merged.get("location_city"),
            region  = merged.get("location_region"),
            country = merged.get("location_country"),
        )
    except Exception as err:           # noqa: BLE001
        logger.warning("Could not build Location: %s — using empty", err)
        return Location()


def _build_links(merged: dict[str, Any]) -> Links:
    """Build a Links from the nested links dict inside merged."""
    raw = merged.get("links") or {}
    try:
        return Links(
            linkedin  = raw.get("linkedin"),
            github    = raw.get("github"),
            portfolio = raw.get("portfolio"),
            other     = raw.get("other") or [],
        )
    except Exception as err:           # noqa: BLE001
        logger.warning("Could not build Links: %s — using empty", err)
        return Links()


def _build_skills(merged: dict[str, Any]) -> list[Skill]:
    """
    Build Skill objects from the enriched skills list.

    The confidence engine (Phase 8) already converted the flat list[str]
    into list[dict] with 'name', 'confidence', 'sources'.
    """
    raw_skills = merged.get("skills") or []
    result: list[Skill] = []

    for item in raw_skills:
        if isinstance(item, str):
            # Fallback: plain string — build with default confidence
            try:
                result.append(Skill(name=item, confidence=0.5, sources=[]))
            except Exception:              # noqa: BLE001
                pass
            continue

        if not isinstance(item, dict):
            continue

        try:
            result.append(Skill(
                name       = str(item.get("name", "")).strip(),
                confidence = float(item.get("confidence", 0.5)),
                sources    = item.get("sources") or [],
            ))
        except Exception as err:           # noqa: BLE001
            logger.debug("Skipping skill item %r: %s", item, err)

    return result


def _build_experience(merged: dict[str, Any]) -> list[Experience]:
    """Build Experience objects from the merged experience list."""
    raw_exp = merged.get("experience") or []
    result: list[Experience] = []

    for item in raw_exp:
        if not isinstance(item, dict):
            continue
        try:
            result.append(Experience(
                company = item.get("company"),
                title   = item.get("title"),
                start   = item.get("start"),
                end     = item.get("end"),
                summary = item.get("summary"),
            ))
        except Exception as err:           # noqa: BLE001
            logger.debug("Skipping experience item %r: %s", item, err)

    return result


def _build_education(merged: dict[str, Any]) -> list[Education]:
    """Build Education objects from the merged education list."""
    raw_edu = merged.get("education") or []
    result: list[Education] = []

    for item in raw_edu:
        if not isinstance(item, dict):
            continue
        try:
            end_year = item.get("end_year")
            if end_year is not None:
                try:
                    end_year = int(end_year)
                except (ValueError, TypeError):
                    logger.debug("Invalid end_year %r — setting None", end_year)
                    end_year = None

            result.append(Education(
                institution = item.get("institution"),
                degree      = item.get("degree"),
                field       = item.get("field"),
                end_year    = end_year,
            ))
        except Exception as err:           # noqa: BLE001
            logger.debug("Skipping education item %r: %s", item, err)

    return result


# ---------------------------------------------------------------------------
# candidate_id generation
# ---------------------------------------------------------------------------

def _derive_candidate_id(merged: dict[str, Any]) -> str:
    """
    Generate a deterministic candidate_id from the merged dict.

    Priority: primary email → name + primary phone → name alone.
    Raises ValueError if none of these are available.
    """
    emails = merged.get("emails") or []
    phones = merged.get("phones") or []
    name   = merged.get("full_name")

    primary_email = emails[0] if emails else None
    primary_phone = phones[0] if phones else None

    return generate_candidate_id(
        normalized_email = primary_email,
        normalized_name  = name,
        normalized_phone = primary_phone,
    )


# ---------------------------------------------------------------------------
# Public entry point — single record
# ---------------------------------------------------------------------------

def build_profile(merged: dict[str, Any]) -> CandidateProfile | None:
    """
    Assemble a merged + scored dict into a validated CandidateProfile.

    Args:
        merged: Output from merger.merge_cluster() after confidence scoring.
                Must contain "_merged_sources" and "_provenance" keys.

    Returns:
        A fully validated CandidateProfile, or None if assembly fails.
        Failure is logged with the candidate's name/email for traceability.
        Never raises.
    """
    name   = merged.get("full_name", "<unknown>")
    emails = merged.get("emails", [])
    identifier = f"{name!r} / {emails[0] if emails else 'no-email'}"

    # --- candidate_id ---
    try:
        candidate_id = _derive_candidate_id(merged)
    except ValueError as err:
        logger.error(
            "Cannot build profile for %s — candidate_id generation failed: %s",
            identifier, err,
        )
        return None

    # --- Sub-models ---
    location   = _build_location(merged)
    links      = _build_links(merged)
    skills     = _build_skills(merged)
    experience = _build_experience(merged)
    education  = _build_education(merged)

    # --- Provenance ---
    raw_prov   = merged.get("_provenance") or []
    prov_list  = deduplicate_provenance(build_provenance_list(raw_prov))

    # Add a 'generated' entry for candidate_id itself
    from src.provenance import record_provenance
    prov_list.append(
        record_provenance("candidate_id", "pipeline", "generated")
    )

    # --- Assemble ---
    try:
        profile = CandidateProfile(
            candidate_id      = candidate_id,
            full_name         = merged.get("full_name") or "",
            emails            = merged.get("emails") or [],
            phones            = merged.get("phones") or [],
            location          = location,
            links             = links,
            headline          = merged.get("headline"),
            years_experience  = merged.get("years_experience"),
            skills            = skills,
            experience        = experience,
            education         = education,
            provenance        = prov_list,
            overall_confidence= float(merged.get("overall_confidence", 0.0)),
        )

        logger.info(
            "Profile built: id=%s name=%r confidence=%.4f "
            "skills=%d exp=%d edu=%d prov=%d",
            profile.candidate_id, profile.full_name,
            profile.overall_confidence,
            len(profile.skills), len(profile.experience),
            len(profile.education), len(profile.provenance),
        )

        return profile

    except Exception as err:           # noqa: BLE001
        # Catch both Pydantic ValidationError and unexpected errors
        logger.error(
            "Profile assembly failed for %s: %s",
            identifier, err,
        )
        return None


# ---------------------------------------------------------------------------
# Public entry point — batch
# ---------------------------------------------------------------------------

def build_all(
    merged_list: list[dict[str, Any]],
) -> list[CandidateProfile]:
    """
    Build canonical profiles for a list of merged dicts.

    Skips any record that fails assembly (returns None from build_profile).
    The batch always continues — one bad record never stops the rest.

    Args:
        merged_list: Output from merger.merge_all() after confidence scoring.

    Returns:
        List of successfully built CandidateProfile objects.
    """
    profiles: list[CandidateProfile] = []
    skipped = 0

    for merged in merged_list:
        profile = build_profile(merged)
        if profile is not None:
            profiles.append(profile)
        else:
            skipped += 1

    if skipped:
        logger.warning(
            "build_all: %d record(s) skipped due to assembly errors "
            "(see ERROR logs above for details)",
            skipped,
        )

    logger.info(
        "build_all: %d profile(s) built, %d skipped",
        len(profiles), skipped,
    )

    return profiles
