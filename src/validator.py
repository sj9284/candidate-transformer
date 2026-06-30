"""
Phase 6 — Field Validation Layer (Input-Side)
=============================================
Validates and normalizes raw field dicts produced by the parsers.

Design rules:
- Runs AFTER parsing, BEFORE identity resolution.
- Invalid value → None. Never crash, never invent.
- Calls Phase 5 normalizers internally — normalization and validation are
  one combined pass. If a normalizer returns None the value is invalid.
- Logs every invalidation: field, raw value, source, reason.
- Identity resolution (Phase 6.5) depends on clean emails — this stage
  must run first.
- Returns the same dict structure with invalid fields set to None
  and a "_validation_log" key containing every rejection record.

Per-field rules:
  email            → normalize_email → None if not RFC-valid
  phone            → normalize_phone → None if not parseable as real number
  linkedin/github  → URL must start with https?://
  portfolio        → URL must start with https?://
  location_country → normalize_country → None if unrecognized
  years_experience → must be float 0.0 <= x <= 60.0
  dates (in exp)   → normalize_date → None if unrecognized format
  skills_raw       → each skill through normalize_skill_name; drop empties
"""

import logging
import re
from typing import Any

from src.normalizer import (
    normalize_country,
    normalize_date,
    normalize_email,
    normalize_phone,
    normalize_skill_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _log_invalid(
    log: list[dict],
    field: str,
    raw_value: Any,
    source: str,
    reason: str,
) -> None:
    """Append one validation rejection record and emit a debug log line."""
    entry = {
        "field":     field,
        "raw_value": str(raw_value)[:120],   # truncate very long values
        "source":    source,
        "reason":    reason,
    }
    log.append(entry)
    logger.debug(
        "INVALID [%s] field=%r raw=%r reason=%s",
        source, field, str(raw_value)[:80], reason,
    )


def _validate_url(
    raw: str | None,
    field: str,
    source: str,
    log: list[dict],
) -> str | None:
    """Validate a URL — must start with http:// or https://."""
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    if not _URL_RE.match(stripped):
        _log_invalid(log, field, raw, source,
                     "URL must start with http:// or https://")
        return None
    return stripped


def _validate_years_experience(
    raw: Any,
    source: str,
    log: list[dict],
) -> float | None:
    """Validate years_experience: must be a number in [0, 60]."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        _log_invalid(log, "years_experience", raw, source,
                     "could not convert to float")
        return None

    if not (0.0 <= value <= 60.0):
        _log_invalid(log, "years_experience", raw, source,
                     f"value {value} outside plausible range [0, 60]")
        return None

    return value


def _validate_skills(
    skills_raw: Any,
    source: str,
    log: list[dict],
) -> list[str]:
    """
    Normalize each skill name in the raw skills list/string.

    Accepts either:
      - list[str]  (resume parser output)
      - str        (comma-separated CSV column)

    Returns a deduplicated list of canonical skill names.
    Empty / un-canonicalizable entries are dropped silently (no log —
    they carry no information worth recording).
    """
    if skills_raw is None:
        return []

    # Coerce to list
    if isinstance(skills_raw, str):
        items = [s.strip() for s in re.split(r"[,;]+", skills_raw) if s.strip()]
    elif isinstance(skills_raw, list):
        items = [str(s).strip() for s in skills_raw if s]
    else:
        _log_invalid(log, "skills_raw", skills_raw, source,
                     "unexpected type: " + type(skills_raw).__name__)
        return []

    canonical: list[str] = []
    seen: set[str] = set()
    for item in items:
        canon = normalize_skill_name(item)
        if canon and canon not in seen:
            seen.add(canon)
            canonical.append(canon)

    return canonical


def _validate_experience_dates(
    experience: list[dict] | None,
    source: str,
    log: list[dict],
) -> list[dict]:
    """
    Normalize start/end date strings inside each experience entry.
    Invalid dates → None (logged). Other fields are passed through as-is.
    """
    if not experience:
        return []

    cleaned: list[dict] = []
    for i, exp in enumerate(experience):
        if not isinstance(exp, dict):
            continue
        entry = dict(exp)   # shallow copy — don't mutate caller's data

        for date_field in ("start", "end"):
            raw_date = entry.get(date_field)
            if raw_date is None:
                continue
            if str(raw_date).lower() in ("present", "current", "now", "ongoing"):
                entry[date_field] = None   # normalise "present" → None (current role)
                continue
            normalized = normalize_date(raw_date)
            if normalized is None:
                _log_invalid(
                    log,
                    f"experience[{i}].{date_field}",
                    raw_date, source,
                    "unrecognized date format",
                )
            entry[date_field] = normalized

        cleaned.append(entry)

    return cleaned


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and normalize one raw field dict from a parser.

    Processes every known field through normalization + validation.
    Unknown fields are passed through untouched (future-proofing).

    Args:
        raw: A dict tagged with "_source" from the CSV or resume parser.

    Returns:
        A new dict with:
          - normalized/validated values (invalid → None)
          - "_source" preserved
          - "_validation_log": list of rejection records for this dict

    Never raises.
    """
    source = raw.get("_source", "unknown")
    log: list[dict] = []

    out: dict[str, Any] = {"_source": source, "_validation_log": log}

    # ---- email ----
    raw_email = raw.get("email") or (raw.get("emails", [None])[0] if isinstance(raw.get("emails"), list) else None)
    norm_email = normalize_email(raw_email)
    if raw_email and norm_email is None:
        _log_invalid(log, "email", raw_email, source, "not a valid email address")
    out["email"] = norm_email

    # ---- emails list (resume parser emits a list) ----
    if "emails" in raw and isinstance(raw["emails"], list):
        validated_emails = []
        for e in raw["emails"]:
            n = normalize_email(e)
            if n:
                validated_emails.append(n)
            elif e:
                _log_invalid(log, "emails[]", e, source, "not a valid email address")
        out["emails"] = validated_emails
    else:
        # Build from the single email field
        out["emails"] = [norm_email] if norm_email else []

    # ---- phone ----
    raw_phones_list = raw.get("phones")
    raw_phone = raw.get("phone") or (raw_phones_list[0] if isinstance(raw_phones_list, list) and raw_phones_list else None)
    norm_phone = normalize_phone(raw_phone)
    if raw_phone and norm_phone is None:
        _log_invalid(log, "phone", raw_phone, source, "unparseable as a valid phone number")
    out["phone"] = norm_phone

    # ---- phones list (resume parser emits a list) ----
    if "phones" in raw and isinstance(raw["phones"], list):
        validated_phones = []
        for p in raw["phones"]:
            n = normalize_phone(p)
            if n:
                validated_phones.append(n)
            elif p:
                _log_invalid(log, "phones[]", p, source, "unparseable as a valid phone number")
        out["phones"] = validated_phones
    else:
        out["phones"] = [norm_phone] if norm_phone else []

    # ---- full_name (pass through; identity resolution needs raw name) ----
    out["full_name"] = raw.get("full_name") or None

    # ---- location ----
    out["location_city"]   = raw.get("location_city") or None
    out["location_region"] = raw.get("location_region") or None

    raw_country = raw.get("location_country") or raw.get("country")
    norm_country = normalize_country(raw_country)
    if raw_country and norm_country is None:
        _log_invalid(log, "location_country", raw_country, source,
                     "unrecognized country name/code")
    out["location_country"] = norm_country

    # ---- links ----
    out["linkedin"]  = _validate_url(raw.get("linkedin"),  "linkedin",  source, log)
    out["github"]    = _validate_url(raw.get("github"),    "github",    source, log)
    out["portfolio"] = _validate_url(raw.get("portfolio"), "portfolio", source, log)

    # ---- headline ----
    out["headline"] = raw.get("headline") or None

    # ---- years_experience ----
    out["years_experience"] = _validate_years_experience(
        raw.get("years_experience"), source, log
    )

    # ---- skills ----
    out["skills"] = _validate_skills(raw.get("skills_raw"), source, log)

    # ---- experience (with date normalization) ----
    out["experience"] = _validate_experience_dates(
        raw.get("experience"), source, log
    )

    # ---- education (pass through; dates are year-only ints, validated by schema) ----
    out["education"] = raw.get("education") or []

    # ---- other fields (current_company, title, notes — pass through) ----
    for passthrough_key in ("current_company", "title", "notes"):
        if passthrough_key in raw:
            out[passthrough_key] = raw[passthrough_key] or None

    if log:
        logger.info(
            "Validation: %d rejection(s) for source=%r — fields: %s",
            len(log), source, [e["field"] for e in log],
        )
    else:
        logger.debug("Validation: no issues for source=%r", source)

    return out


def validate_all(raw_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validate a list of raw dicts.

    Args:
        raw_dicts: Output from parse_csv() or [parse_resume()].

    Returns:
        List of validated dicts. Same length as input — never drops records.
    """
    return [validate_dict(d) for d in raw_dicts]
