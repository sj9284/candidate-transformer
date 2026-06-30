"""
Phase 11.5 — Output Schema Validator
======================================
Validates a projected JSON result against the config that produced it.

This is the output-side validator — completely separate from Phase 6's
input-side validator. It checks the result of projection, not raw parser
output.

Validation checks:
  1. Required field present — if required=true, the key must exist and
     its value must not be None.
  2. Type match — declared 'type' in the config must match the actual
     Python type of the projected value.

Type mapping (config 'type' string → Python type):
  string    → str
  string[]  → list   (elements not individually checked — keep it simple)
  number    → int or float
  object    → dict
  object[]  → list
  boolean   → bool

Return contract:
  - Returns a ValidationResult with a list of violations (strings) and
    a should_abort flag.
  - should_abort=True only when a required=true field is missing/None or
    has the wrong type.
  - Non-required type mismatches are violations but do NOT set should_abort.
  - Never raises — all errors are captured as violation strings.

Design rationale (why not jsonschema):
  The config already declares 'type' and 'required' per field.
  Checking against that same config is simpler, more direct, and avoids
  pulling in a heavy dependency for a task this focused.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type system
# ---------------------------------------------------------------------------

# Maps config 'type' string → (human label, Python type(s) to isinstance-check)
_TYPE_MAP: dict[str, tuple[str, type | tuple[type, ...]]] = {
    "string":   ("string",   str),
    "string[]": ("list",     list),
    "number":   ("number",   (int, float)),
    "object":   ("object",   dict),
    "object[]": ("list",     list),
    "boolean":  ("boolean",  bool),
}


def _type_matches(value: Any, declared_type: str) -> bool:
    """
    Return True if value's Python type matches the declared config type.
    Returns True for unknown/unrecognised type strings (we don't fail on
    things we can't check).
    """
    if declared_type not in _TYPE_MAP:
        return True   # unknown type — no check

    _, expected_python_type = _TYPE_MAP[declared_type]
    # Special case: bool is a subclass of int in Python, so check bool first
    if declared_type == "number" and isinstance(value, bool):
        return False   # bool is not a number in our domain
    return isinstance(value, expected_python_type)


def _type_label(declared_type: str) -> str:
    """Return a human-readable label for a config type string."""
    return _TYPE_MAP.get(declared_type, (declared_type, None))[0]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    Result of validating one projected record against its config.

    Attributes:
        violations:   List of human-readable violation strings.
        should_abort: True if any required=true field failed (missing or
                      wrong type). The caller should not write this record.
        warnings:     List of non-fatal issues (type mismatches on optional
                      fields). The record can still be written.
    """
    violations:   list[str] = field(default_factory=list)
    warnings:     list[str] = field(default_factory=list)
    should_abort: bool       = False

    @property
    def is_valid(self) -> bool:
        """True if there are no abort-level violations."""
        return not self.should_abort

    def summary(self) -> str:
        """One-line summary string."""
        if self.is_valid and not self.warnings:
            return "OK"
        parts = []
        if self.violations:
            parts.append(f"{len(self.violations)} violation(s)")
        if self.warnings:
            parts.append(f"{len(self.warnings)} warning(s)")
        status = "ABORT" if self.should_abort else "WARN"
        return f"{status}: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------

def validate_output(
    projected: dict[str, Any],
    config: dict[str, Any],
) -> ValidationResult:
    """
    Validate a projected dict against its originating config.

    Args:
        projected: Output from projector.project_profile().
        config:    The same config dict used to produce 'projected'.

    Returns:
        ValidationResult with violations, warnings, and should_abort flag.
        Never raises.
    """
    result = ValidationResult()

    fields_config = config.get("fields", [])

    for field_entry in fields_config:
        output_key    = field_entry.get("path")
        declared_type = field_entry.get("type")
        is_required   = bool(field_entry.get("required", False))

        if not output_key:
            continue   # malformed config entry — skip silently

        # ---- Check 1: Required field present and non-null ----
        key_present = output_key in projected
        value       = projected.get(output_key)
        value_null  = value is None

        if is_required and (not key_present or value_null):
            msg = (
                f"REQUIRED field missing or null: '{output_key}'"
                + (" (key absent)" if not key_present else " (value is null)")
            )
            result.violations.append(msg)
            result.should_abort = True
            logger.error("Output validation: %s", msg)
            continue   # no point checking type if value is absent/null

        # ---- Check 2: Type match (only when value is present and non-null) ----
        if declared_type and key_present and not value_null:
            if not _type_matches(value, declared_type):
                actual_type  = type(value).__name__
                expected_lbl = _type_label(declared_type)
                msg = (
                    f"Type mismatch for '{output_key}': "
                    f"expected {expected_lbl} ({declared_type}), "
                    f"got {actual_type} ({value!r:.60})"
                )
                if is_required:
                    result.violations.append(msg)
                    result.should_abort = True
                    logger.error("Output validation: %s", msg)
                else:
                    result.warnings.append(msg)
                    logger.warning("Output validation: %s", msg)

    # ---- Also check include_confidence / include_provenance are present ----
    if config.get("include_confidence") and "overall_confidence" not in projected:
        msg = "include_confidence=true but 'overall_confidence' absent from output"
        result.warnings.append(msg)
        logger.warning("Output validation: %s", msg)

    if config.get("include_provenance") and "provenance" not in projected:
        msg = "include_provenance=true but 'provenance' absent from output"
        result.warnings.append(msg)
        logger.warning("Output validation: %s", msg)

    logger.debug(
        "Output validation complete: %s  violations=%d warnings=%d",
        result.summary(), len(result.violations), len(result.warnings),
    )

    return result


# ---------------------------------------------------------------------------
# Batch validator
# ---------------------------------------------------------------------------

def validate_all_outputs(
    projected_list: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[tuple[dict[str, Any], ValidationResult]]:
    """
    Validate all projected records in a batch.

    Args:
        projected_list: Output from projector.project_all().
        config:         The same config used for projection.

    Returns:
        List of (projected_dict, ValidationResult) pairs.
        Records that fail (should_abort=True) should be excluded from
        the final write by the caller.

    Never raises.
    """
    results = []
    abort_count = 0

    for projected in projected_list:
        vr = validate_output(projected, config)
        results.append((projected, vr))
        if not vr.is_valid:
            abort_count += 1

    if abort_count:
        logger.warning(
            "validate_all_outputs: %d/%d record(s) failed validation "
            "and will not be written",
            abort_count, len(projected_list),
        )
    else:
        logger.info(
            "validate_all_outputs: all %d record(s) passed",
            len(projected_list),
        )

    return results


def filter_valid(
    validated: list[tuple[dict[str, Any], ValidationResult]],
) -> list[dict[str, Any]]:
    """
    Filter a validate_all_outputs result to only the records that passed.

    Args:
        validated: Output from validate_all_outputs().

    Returns:
        List of projected dicts where ValidationResult.is_valid is True.
    """
    return [projected for projected, vr in validated if vr.is_valid]
