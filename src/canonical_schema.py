"""
Phase 2 — Canonical Schema
==========================
Defines the single source-of-truth data model for a candidate profile.

Design principles:
- All nested models default to empty list / None so partial data never breaks instantiation.
- candidate_id is deterministically derived from normalized email (sha256[:16]).
  Never use UUID4 — same inputs must always produce the same id (determinism constraint).
- This schema is internal. Downstream consumers always see a projected view (Phase 11).
"""

import hashlib
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Nested models
# ---------------------------------------------------------------------------

class Location(BaseModel):
    """Geographic location of the candidate."""

    city: str | None = None
    region: str | None = None          # state / province
    country: str | None = None         # ISO-3166 alpha-2 (e.g. "US", "IN")

    model_config = {"extra": "ignore"}


class Links(BaseModel):
    """Online presence links for the candidate."""

    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None
    other: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class Skill(BaseModel):
    """
    A single skill with its own confidence score.

    Per-skill confidence is separate from overall_confidence because
    extraction risk differs: a skill mentioned in one unstructured source
    is less reliable than one confirmed across CSV and resume.
    """

    name: str                                       # canonical lowercase name
    confidence: float = Field(ge=0.0, le=1.0)      # 0.0 – 1.0
    sources: list[str] = Field(default_factory=list)  # source filenames that mentioned this skill

    model_config = {"extra": "ignore"}

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Skill name must not be empty")
        return v


class Experience(BaseModel):
    """A single work-experience entry."""

    company: str | None = None
    title: str | None = None
    start: str | None = None    # YYYY-MM  (e.g. "2021-03")
    end: str | None = None      # YYYY-MM  or None when current role
    summary: str | None = None

    model_config = {"extra": "ignore"}


class Education(BaseModel):
    """A single education entry."""

    institution: str | None = None
    degree: str | None = None       # e.g. "B.S.", "M.S.", "Ph.D."
    field: str | None = None        # e.g. "Computer Science"
    cgpa: str | None = None
    start_year: int | None = None
    end_year: int | None = None     # graduation year

    model_config = {"extra": "ignore"}

    @field_validator("end_year")
    @classmethod
    def year_in_range(cls, v: int | None) -> int | None:
        if v is not None and not (1900 <= v <= 2100):
            raise ValueError(f"end_year {v} is outside plausible range 1900–2100")
        return v


class ProvenanceEntry(BaseModel):
    """
    Records exactly where one field's value came from.

    method values (exhaustive):
      csv_direct            – taken directly from CSV column
      regex_extract         – extracted from resume/free-text by regex
      merge_conflict_csv_won     – scalar conflict; CSV preferred by policy
      merge_conflict_resume_won  – scalar conflict; resume preferred by policy
      union_list            – list field; all sources merged and deduplicated
      default               – no source had a value; field is None / empty
    """

    field: str       # canonical field name, e.g. "full_name", "emails"
    value: Any | None = None
    source: str      # source filename, e.g. "recruiter.csv", "resume.pdf"
    method: str      # one of the values listed above
    confidence: float | None = None

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------

class CandidateProfile(BaseModel):
    """
    The canonical, fully validated representation of one candidate.

    This is the single source of truth produced by the pipeline.
    Nothing downstream modifies this object — they only read from it
    via the projection layer (Phase 11).
    """

    # --- Identity ---
    candidate_id: str = Field(
        description=(
            "Deterministic identifier: sha256(normalized_primary_email)[:16]. "
            "If no email: sha256(normalized_full_name + normalized_primary_phone)[:16]. "
            "Never UUID4 — same inputs must always yield the same id."
        )
    )
    full_name: str

    # --- Contact ---
    emails: list[str] = Field(default_factory=list)    # normalized lowercase
    phones: list[str] = Field(default_factory=list)    # E.164 format

    # --- Location & Links ---
    location: Location = Field(default_factory=Location)
    links: Links = Field(default_factory=Links)

    # --- Professional summary ---
    headline: str | None = None
    years_experience: float | None = Field(
        default=None,
        ge=0.0,
        le=60.0,
        description="Best-effort figure; may be None for resumes with unusual date formats.",
    )

    # --- Structured sections ---
    skills: list[Skill] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)

    # --- Pipeline metadata ---
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    overall_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Aggregate confidence score: base_score(source_count) × "
            "avg(source_reliability_weights). See confidence.py for formula."
        ),
    )

    model_config = {"extra": "ignore"}

    # ------------------------------------------------------------------
    # Convenience helpers (read-only; do not mutate the profile)
    # ------------------------------------------------------------------

    def primary_email(self) -> str | None:
        """Return the first email in the list, or None."""
        return self.emails[0] if self.emails else None

    def primary_phone(self) -> str | None:
        """Return the first phone in the list, or None."""
        return self.phones[0] if self.phones else None

    def skill_names(self) -> list[str]:
        """Return a flat list of canonical skill names."""
        return [s.name for s in self.skills]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (used by the projection layer)."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# candidate_id generation  (standalone function — import and call from
#                            profile_builder.py, not inside the model)
# ---------------------------------------------------------------------------

def generate_candidate_id(
    normalized_email: str | None,
    normalized_name: str | None = None,
    normalized_phone: str | None = None,
) -> str:
    """
    Produce a deterministic 16-character hex candidate_id.

    Priority:
      1. sha256(normalized_email)[:16]            — preferred
      2. sha256(normalized_name + normalized_phone)[:16]  — fallback
      3. sha256(normalized_name)[:16]             — last resort

    Args:
        normalized_email: Lowercase, stripped email, or None.
        normalized_name:  Lowercase, stripped full name, or None.
        normalized_phone: E.164 phone string, or None.

    Returns:
        16-character lowercase hex string.

    Raises:
        ValueError: If all three inputs are None or empty.
    """
    if normalized_email:
        key = normalized_email.strip().lower()
    elif normalized_name and normalized_phone:
        key = (normalized_name.strip().lower() + normalized_phone.strip())
    elif normalized_name:
        key = normalized_name.strip().lower()
    else:
        raise ValueError(
            "Cannot generate candidate_id: email, name, and phone are all absent. "
            "At least one must be present."
        )

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
