"""
Phase 9 — Provenance Tracker
==============================
Converts raw provenance dicts from the Merge Engine into typed
ProvenanceEntry objects, and provides helpers used by Phase 10
when assembling the canonical CandidateProfile.

Design rules:
- Every field write in the pipeline goes through here (via the merge
  engine, which calls _prov() and hands back a list in "_provenance").
- Only the WINNING source is recorded for scalar conflicts — not all
  candidates. This keeps the provenance list actionable, not noisy.
- "default" entries (source="none", method="default") are preserved so
  a reviewer can see which fields had no data at all.
- Invalid / malformed raw entries are logged and skipped — never crash.
- Provides record_provenance() for any stage that needs to write
  provenance outside the merge engine (e.g. Phase 10 adding a
  candidate_id provenance entry).

Method vocabulary (exhaustive, must match merger.py):
  csv_direct                — value taken directly from CSV column
  regex_extract             — value extracted from resume by regex
  merge_conflict_csv_won    — scalar conflict; CSV preferred by policy
  merge_conflict_resume_won — scalar conflict; resume preferred by policy
  union_list                — list field; all sources merged+deduped
  default                   — no source had a value; field is None/empty
  generated                 — value computed by the pipeline (e.g. candidate_id)
"""

import logging
from typing import Any

from src.canonical_schema import ProvenanceEntry

logger = logging.getLogger(__name__)

# Valid method strings — used for validation
VALID_METHODS = frozenset({
    "csv_direct",
    "regex_extract",
    "merge_conflict_csv_won",
    "merge_conflict_resume_won",
    "union_list",
    "default",
    "generated",
})


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def record_provenance(field: str, source: str, method: str) -> ProvenanceEntry:
    """
    Create a single ProvenanceEntry.

    Args:
        field:  Canonical field name (e.g. "full_name", "emails").
        source: Source filename (e.g. "recruiter.csv", "resume.pdf").
                Use "none" when the field has no source (method="default").
                Use "pipeline" for computed fields (method="generated").
        method: One of the VALID_METHODS strings.

    Returns:
        A validated ProvenanceEntry instance.
    """
    if method not in VALID_METHODS:
        logger.warning(
            "Unknown provenance method %r for field=%r — recording anyway",
            method, field,
        )
    return ProvenanceEntry(field=field, source=source, method=method)


# ---------------------------------------------------------------------------
# Batch builder (used by Phase 10)
# ---------------------------------------------------------------------------

def build_provenance_list(
    raw_provenance: list[dict[str, Any]],
) -> list[ProvenanceEntry]:
    """
    Convert the raw provenance list from merger._provenance into typed
    ProvenanceEntry objects.

    Args:
        raw_provenance: List of dicts, each with keys "field", "source",
                        "method". Produced by merger.merge_cluster().

    Returns:
        List of ProvenanceEntry objects. Malformed entries are skipped
        and logged. Never raises.
    """
    entries: list[ProvenanceEntry] = []

    for i, raw in enumerate(raw_provenance):
        if not isinstance(raw, dict):
            logger.warning("Provenance entry %d is not a dict — skipping: %r", i, raw)
            continue

        field  = raw.get("field")
        source = raw.get("source")
        method = raw.get("method")

        if not field or not source or not method:
            logger.warning(
                "Provenance entry %d missing required keys "
                "(field=%r, source=%r, method=%r) — skipping",
                i, field, source, method,
            )
            continue

        try:
            entry = record_provenance(str(field), str(source), str(method))
            entries.append(entry)
        except Exception as err:           # noqa: BLE001
            logger.warning("Could not build ProvenanceEntry %d: %s", i, err)
            continue

    return entries


# ---------------------------------------------------------------------------
# Deduplication (optional cleanup step)
# ---------------------------------------------------------------------------

def deduplicate_provenance(
    entries: list[ProvenanceEntry],
) -> list[ProvenanceEntry]:
    """
    Remove exact duplicate (field, source, method) triples.

    Preserves order of first occurrence. Useful when union_list entries
    can appear more than once for the same (field, source) pair.
    """
    seen: set[tuple[str, str, str]] = set()
    result: list[ProvenanceEntry] = []

    for e in entries:
        key = (e.field, e.source, e.method)
        if key not in seen:
            seen.add(key)
            result.append(e)

    return result


# ---------------------------------------------------------------------------
# Introspection helpers (used by CLI / logging)
# ---------------------------------------------------------------------------

def provenance_for_field(
    entries: list[ProvenanceEntry],
    field: str,
) -> list[ProvenanceEntry]:
    """Return all provenance entries for a given field name."""
    return [e for e in entries if e.field == field]


def sources_for_field(
    entries: list[ProvenanceEntry],
    field: str,
) -> list[str]:
    """Return the list of source filenames that contributed to a field."""
    return [e.source for e in provenance_for_field(entries, field)]


def summarize(entries: list[ProvenanceEntry]) -> dict[str, list[str]]:
    """
    Return a compact summary: {field: [method@source, ...]}
    Useful for debug logging and the CLI --verbose flag.

    Example:
        {
          "full_name":  ["merge_conflict_csv_won@recruiter.csv"],
          "emails":     ["union_list@recruiter.csv", "union_list@resume.pdf"],
          "experience": ["regex_extract@resume.pdf"],
        }
    """
    summary: dict[str, list[str]] = {}
    for e in entries:
        summary.setdefault(e.field, []).append(f"{e.method}@{e.source}")
    return summary
