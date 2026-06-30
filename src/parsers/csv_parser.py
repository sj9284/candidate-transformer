"""
Phase 3 — CSV Parser
====================
Reads a recruiter CSV export and returns a list of raw dicts.

Design rules:
- Output: list[dict], each dict tagged {"_source": filepath}
- NO normalization or validation here — raw values only
- Never crash on bad data; log and continue
- Missing file → log + return []
- Missing column → fill with None, log once
- Encoding errors → skip that row, log it
- Empty string values are converted to None (they carry no information)
"""

import csv
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected columns and their canonical mapping to internal field names.
# Any CSV column NOT in this map is still passed through under its original
# name — we don't silently drop unknown columns.
# ---------------------------------------------------------------------------
COLUMN_MAP: dict[str, str] = {
    "name":             "full_name",
    "email":            "email",
    "phone":            "phone",
    "current_company":  "current_company",
    "title":            "title",
    "location_city":    "location_city",
    "location_country": "location_country",
    "linkedin":         "linkedin",
    "github":           "github",
    "years_experience": "years_experience",
    "skills":           "skills_raw",   # comma-separated string; normalizer will split
    "notes":            "notes",
}


def _remap_row(row: dict[str, str]) -> dict[str, Any]:
    """
    Remap CSV column names to internal field names.
    Unknown columns are kept as-is.
    Empty strings → None.
    """
    remapped: dict[str, Any] = {}
    for csv_col, value in row.items():
        key = COLUMN_MAP.get(csv_col, csv_col)          # remap or keep original
        remapped[key] = value.strip() if value and value.strip() else None
    return remapped


def parse_csv(filepath: str) -> list[dict[str, Any]]:
    """
    Read a recruiter CSV file and return a list of raw field dicts.

    Each dict contains:
      - All CSV columns (remapped via COLUMN_MAP, unknown cols kept as-is)
      - "_source": filepath  (provenance tag used by all downstream stages)

    Args:
        filepath: Path to the recruiter CSV file.

    Returns:
        List of raw dicts. Empty list on any file-level error.
        Never raises — all errors are logged.
    """
    results: list[dict[str, Any]] = []

    # --- File existence check ---
    if not os.path.exists(filepath):
        logger.error("CSV file not found: %s — skipping source", filepath)
        return []

    if os.path.getsize(filepath) == 0:
        logger.warning("CSV file is empty: %s — skipping source", filepath)
        return []

    try:
        with open(filepath, newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)

            # Validate that the file has at least a header
            if reader.fieldnames is None:
                logger.error("CSV file has no header row: %s", filepath)
                return []

            fieldnames = [f.strip() for f in reader.fieldnames if f]
            logger.debug("CSV columns detected: %s", fieldnames)

            # Warn once for any expected columns that are missing
            expected = set(COLUMN_MAP.keys())
            present  = set(fieldnames)
            missing  = expected - present
            if missing:
                logger.warning(
                    "CSV %s is missing expected columns: %s — those fields will be None",
                    filepath, sorted(missing)
                )

            for line_num, row in enumerate(reader, start=2):   # start=2: row 1 is header
                try:
                    remapped = _remap_row(dict(row))
                    remapped["_source"] = filepath
                    results.append(remapped)
                    logger.debug("Row %d parsed: %s", line_num, remapped.get("full_name"))

                except Exception as row_err:                    # noqa: BLE001
                    # One bad row must never abort the whole file
                    logger.warning(
                        "CSV %s row %d could not be parsed — skipping: %s",
                        filepath, line_num, row_err
                    )
                    continue

    except UnicodeDecodeError as enc_err:
        # Should not happen (errors="replace"), but guard anyway
        logger.error("Encoding error reading %s: %s", filepath, enc_err)
        return []

    except OSError as io_err:
        logger.error("Could not open %s: %s", filepath, io_err)
        return []

    logger.info("CSV parser: %d rows loaded from %s", len(results), filepath)
    return results
