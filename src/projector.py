"""
Phase 11 — Projection Layer
============================
Transforms a CandidateProfile into a custom JSON shape driven by a
runtime config. Keeps a clean separation between the canonical internal
record (Phase 10) and the output shape consumers receive.

Config schema (see configs/custom_projection.json for a full example):
    {
      "fields": [
        { "path": "full_name",      "type": "string",   "required": true  },
        { "path": "primary_email",  "from": "emails[0]","type": "string",  "required": true },
        { "path": "phone",          "from": "phones[0]","type": "string",  "normalize": "E164" },
        { "path": "skills",         "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
      ],
      "include_confidence": true,
      "include_provenance": false,
      "on_missing": "null"
    }

Path resolution mini-DSL (three patterns, exhaustive):
  Pattern            Example            Behaviour
  ────────────────── ─────────────────  ──────────────────────────────────────
  field_name         full_name          Direct attribute access → scalar
  field[N]           emails[0]          Index into list → scalar or missing
  field[].subfield   skills[].name      Map over list, extract sub-key → list

Per-field processing order:
  1. Resolve path via mini-DSL
  2. If missing → apply on_missing (field-level overrides global)
  3. If normalize key set → call normalizer from Phase 5 (no copy, reused)
  4. Write to output under 'path' key

on_missing modes:
  null   Write null for the key
  omit   Drop the key from output
  error  Log field + candidate; skip this record; continue batch

Toggles (applied last, after field selection):
  include_confidence  append overall_confidence to output
  include_provenance  append provenance list to output
"""

import json
import logging
import re
from typing import Any

from src.canonical_schema import CandidateProfile
from src.normalizer import get_normalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution mini-DSL
# ---------------------------------------------------------------------------

# Three compiled patterns — order matters: try most specific first
_PATTERN_INDEX  = re.compile(r"^(\w+)\[(\d+)\]$")          # emails[0]
_PATTERN_MAP    = re.compile(r"^([\w]+)\[\]\.([\w]+)$")     # skills[].name
_PATTERN_SIMPLE = re.compile(r"^[\w.]+$")                   # full_name  or  location.city


def _resolve_path(path: str, data: dict[str, Any]) -> tuple[Any, bool]:
    """
    Resolve a path string against a flat candidate dict.

    Returns:
        (value, found) where found=False means the path resolved to nothing
        (key missing, index out of range, etc.).

    Never raises.
    """
    # Pattern 1: field[N]  — index into a list
    m = _PATTERN_INDEX.match(path)
    if m:
        field, idx = m.group(1), int(m.group(2))
        lst = data.get(field)
        if not isinstance(lst, list) or idx >= len(lst):
            return None, False
        val = lst[idx]
        return val, (val is not None)

    # Pattern 2: field[].subfield  — map over list, extract sub-key
    m = _PATTERN_MAP.match(path)
    if m:
        field, subfield = m.group(1), m.group(2)
        lst = data.get(field)
        if not isinstance(lst, list):
            return [], True   # empty list is a valid result for list paths
        result = []
        for item in lst:
            if isinstance(item, dict):
                v = item.get(subfield)
                if v is not None:
                    result.append(v)
        return result, True   # empty list is still "found"

    # Pattern 3: simple field name (also supports dot notation one level deep)
    if "." in path:
        parts = path.split(".", 1)
        parent = data.get(parts[0])
        if isinstance(parent, dict):
            val = parent.get(parts[1])
            return val, (val is not None)
        return None, False

    if _PATTERN_SIMPLE.match(path):
        val = data.get(path)
        return val, (val is not None)

    logger.warning("Unrecognized path pattern: %r — skipping field", path)
    return None, False


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str | None) -> dict[str, Any]:
    """
    Load and validate a projection config JSON file.

    Args:
        config_path: Path to JSON config file, or None for default
                     (returns a passthrough config that outputs all
                     canonical fields with confidence + provenance).

    Returns:
        Parsed config dict.

    Raises:
        ValueError: If the file cannot be read or parsed.
    """
    if config_path is None:
        return _default_config()

    try:
        with open(config_path, encoding="utf-8") as fh:
            config = json.load(fh)
    except FileNotFoundError:
        raise ValueError(f"Config file not found: {config_path}")
    except json.JSONDecodeError as err:
        raise ValueError(f"Config file is not valid JSON: {config_path} — {err}")

    if "fields" not in config:
        raise ValueError(f"Config missing required 'fields' key: {config_path}")

    return config


def _default_config() -> dict[str, Any]:
    """
    Passthrough config: output all canonical fields unchanged.
    Used when --config is omitted from the CLI.
    """
    return {
        "fields": [
            {"path": "candidate_id",     "type": "string",   "required": True},
            {"path": "full_name",        "type": "string",   "required": True},
            {"path": "emails",           "type": "string[]", "required": False},
            {"path": "phones",           "type": "string[]", "required": False},
            {"path": "location",         "type": "object",   "required": False},
            {"path": "links",            "type": "object",   "required": False},
            {"path": "headline",         "type": "string",   "required": False},
            {"path": "years_experience", "type": "number",   "required": False},
            {"path": "skills",           "type": "object[]", "required": False},
            {"path": "experience",       "type": "object[]", "required": False},
            {"path": "education",        "type": "object[]", "required": False},
        ],
        "include_confidence": True,
        "include_provenance": True,
        "on_missing": "null",
    }


# ---------------------------------------------------------------------------
# Single-record projection
# ---------------------------------------------------------------------------

class ProjectionError(Exception):
    """Raised internally when on_missing='error' fires for a required field."""
    def __init__(self, field_path: str, output_key: str) -> None:
        self.field_path = field_path
        self.output_key = output_key
        super().__init__(f"Missing required field: {output_key!r} (from path {field_path!r})")


def _is_missing(value: Any, path: str) -> bool:
    """
    Determine whether a resolved value counts as 'missing'.

    List paths (field[].subfield) return [] when the source list is
    empty — that is not missing, it's a valid empty result.
    Scalar paths return None when the key is absent — that IS missing.
    """
    if _PATTERN_MAP.match(path):
        return False   # [] is valid for list paths
    return value is None


def project_profile(
    profile: CandidateProfile,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Transform one CandidateProfile into a custom JSON-serialisable dict.

    Args:
        profile: A validated CandidateProfile from Phase 10.
        config:  Parsed projection config dict.

    Returns:
        Projected dict, or None if on_missing='error' fired for any field
        in this record (per-record failure — batch continues).

    Never raises.
    """
    data = profile.to_dict()
    output: dict[str, Any] = {}

    global_on_missing = config.get("on_missing", "null")
    fields_config     = config.get("fields", [])

    for field_entry in fields_config:
        output_key  = field_entry.get("path")
        source_path = field_entry.get("from", output_key)   # 'from' overrides 'path'
        normalize   = field_entry.get("normalize")
        on_missing  = field_entry.get("on_missing", global_on_missing)

        if not output_key or not source_path:
            logger.warning("Field entry missing 'path': %r — skipping", field_entry)
            continue

        # --- Step 1: resolve path ---
        try:
            value, found = _resolve_path(source_path, data)
        except Exception as err:          # noqa: BLE001
            logger.warning("Path resolution error for %r: %s", source_path, err)
            value, found = None, False

        # --- Step 2: handle missing ---
        if not found or _is_missing(value, source_path):
            if on_missing == "omit":
                continue
            elif on_missing == "error":
                logger.error(
                    "on_missing=error: field %r (path=%r) is absent for "
                    "candidate %r — skipping this record",
                    output_key, source_path, profile.full_name,
                )
                return None
            else:   # "null" (default)
                output[output_key] = None
                continue

        # --- Step 3: re-normalize if requested ---
        if normalize:
            normalizer_fn = get_normalizer(normalize)
            if normalizer_fn is not None:
                if isinstance(value, list):
                    # Apply per-element for list values (e.g. skills[].name)
                    value = [
                        normalizer_fn(item) for item in value
                        if normalizer_fn(item) is not None
                    ]
                else:
                    value = normalizer_fn(value)

        # --- Step 4: write to output ---
        output[output_key] = value

    # --- Toggles (applied last) ---
    if config.get("include_confidence", False):
        output["overall_confidence"] = profile.overall_confidence

    if config.get("include_provenance", False):
        output["provenance"] = [
            {"field": p.field, "source": p.source, "method": p.method}
            for p in profile.provenance
        ]

    return output


# ---------------------------------------------------------------------------
# Batch projection
# ---------------------------------------------------------------------------

def project_all(
    profiles: list[CandidateProfile],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Project a list of CandidateProfiles using the given config.

    Skips records where project_profile() returns None (on_missing=error
    fired). The batch always continues.

    Args:
        profiles: List of CandidateProfile objects from Phase 10.
        config:   Parsed projection config.

    Returns:
        List of projected dicts (may be shorter than profiles if any
        records were skipped due to on_missing=error).
    """
    results: list[dict[str, Any]] = []
    skipped = 0

    for profile in profiles:
        result = project_profile(profile, config)
        if result is not None:
            results.append(result)
        else:
            skipped += 1

    if skipped:
        logger.warning(
            "project_all: %d record(s) skipped due to on_missing=error",
            skipped,
        )

    logger.info(
        "project_all: %d projected, %d skipped (config fields=%d)",
        len(results), skipped, len(config.get("fields", [])),
    )

    return results
