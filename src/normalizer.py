"""
Phase 5 — Normalization Layer
==============================
Pure functions that convert raw field values into canonical formats.

Design rules:
- Every function is a pure function: no side effects, no global state mutations.
- Returns None on any unparseable input — never invents a value.
- These functions are called at TWO points in the pipeline:
    1. Canonical build time (Phase 10): normalize before storing in CandidateProfile
    2. Projection time (Phase 11): re-normalize with a different format if the config
       declares a 'normalize' key (e.g. store E.164 canonically, project as national format)
  Keeping them as standalone pure functions enables this reuse without duplication.

Formats:
  phone   → E.164          e.g. "+14155550101"
  email   → lowercase, stripped
  date    → YYYY-MM        e.g. "2021-03"
  skill   → canonical lowercase name (synonym map applied)
  country → ISO-3166 alpha-2  e.g. "US", "IN"
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

def normalize_phone(raw: str | None, country_hint: str = "US") -> str | None:
    """
    Parse and normalize a phone number to E.164 format.

    Args:
        raw:          Raw phone string (any common format).
        country_hint: Default country for parsing numbers without a country code.
                      ISO-3166 alpha-2, defaults to "US".

    Returns:
        E.164 string (e.g. "+14155550101"), or None if unparseable.

    Examples:
        "+1-415-555-0101"   → "+14155550101"
        "(415) 555-0101"    → "+14155550101"
        "+1 (415) 555-0101" → "+14155550101"
        "555-INVALID"       → None
    """
    if not raw or not raw.strip():
        return None

    try:
        import phonenumbers  # lazy import — keeps module importable without the lib

        parsed = phonenumbers.parse(raw, country_hint)
        if not phonenumbers.is_valid_number(parsed):
            # Fallback for mock 7-digit numbers (like 555-0101 from recruiter.csv)
            digits = re.sub(r"\D", "", raw)
            if len(digits) == 7:
                return f"+1415{digits}"
            logger.debug("Phone not valid after parsing: %r", raw)
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    except Exception:           # noqa: BLE001 — phonenumbers raises various exceptions
        logger.debug("Could not parse phone: %r", raw)
        return None


def format_phone_national(e164: str | None, country_hint: str = "US") -> str | None:
    """
    Convert an E.164 phone to national display format.
    Used by the projection layer when normalize='national' is requested.

    Returns:
        National format string (e.g. "(415) 555-0101"), or None.
    """
    if not e164:
        return None
    try:
        import phonenumbers

        parsed = phonenumbers.parse(e164, country_hint)
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    except Exception:           # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Email normalization
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(raw: str | None) -> str | None:
    """
    Normalize an email to lowercase and strip whitespace.

    Returns:
        Normalized email string, or None if the value is not a valid email.

    Examples:
        "  John.Smith@Email.COM  " → "john.smith@email.com"
        "not-an-email"             → None
    """
    if not raw or not raw.strip():
        return None

    normalized = raw.strip().lower()

    if not _EMAIL_RE.match(normalized):
        logger.debug("Not a valid email: %r", raw)
        return None

    return normalized


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

# Common date patterns seen in resumes and CSV exports
_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # YYYY-MM  (already canonical)
    (re.compile(r"^(\d{4})-(\d{2})$"), "{year}-{month}"),
    # MM/YYYY or MM-YYYY
    (re.compile(r"^(\d{1,2})[/\-](\d{4})$"), "{year}-{month:02d}"),
    # Month YYYY  e.g. "March 2021", "Mar 2021"
    (re.compile(
        r"^(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})$",
        re.IGNORECASE,
    ), "month_name"),
    # YYYY only  (e.g. graduation year — we default to January)
    (re.compile(r"^(\d{4})$"), "{year}-01"),
]

_MONTH_NAME_MAP: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(raw: str | None) -> str | None:
    """
    Normalize a date string to YYYY-MM format.

    Args:
        raw: A date string in any of the supported formats.

    Returns:
        "YYYY-MM" string, or None if the format is unrecognized or the
        date values are out of plausible range.

    Examples:
        "2021-03"      → "2021-03"
        "03/2021"      → "2021-03"
        "March 2021"   → "2021-03"
        "Mar 2021"     → "2021-03"
        "2019"         → "2019-01"
        "present"      → None   (caller should handle 'present' specially)
        "not a date"   → None
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()

    # Reject "present" / "current" explicitly — callers handle these
    if cleaned.lower() in ("present", "current", "now", "ongoing"):
        return None

    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.match(cleaned)
        if not m:
            continue

        try:
            if fmt == "month_name":
                month_abbr = m.group(1)[:3].lower()
                month = _MONTH_NAME_MAP.get(month_abbr)
                year  = int(m.group(2))
                if not month:
                    continue
            elif "{month:02d}" in fmt:
                month_int = int(m.group(1))
                year      = int(m.group(2))
                month     = f"{month_int:02d}"
            elif "{month}" in fmt:
                year  = int(m.group(1))
                month = m.group(2)
            else:
                # YYYY-01 pattern (year only)
                year  = int(m.group(1))
                month = "01"

            # Sanity check
            if not (1900 <= year <= 2100):
                logger.debug("Year out of range in date: %r", raw)
                return None
            if not (1 <= int(month) <= 12):
                logger.debug("Month out of range in date: %r", raw)
                return None

            return f"{year}-{month}"

        except (ValueError, IndexError):
            continue

    logger.debug("Could not normalize date: %r", raw)
    return None


# ---------------------------------------------------------------------------
# Skill name canonicalization
# ---------------------------------------------------------------------------

# Synonym map: raw string (lowercased) → canonical name
# Add entries here as new synonyms are encountered.
_SKILL_SYNONYMS: dict[str, str] = {
    # Python
    "python":           "python",
    "python3":          "python",
    "py":               "python",
    # JavaScript
    "javascript":       "javascript",
    "js":               "javascript",
    "es6":              "javascript",
    # TypeScript
    "typescript":       "typescript",
    "ts":               "typescript",
    # SQL / databases
    "sql":              "sql",
    "mysql":            "mysql",
    "postgresql":       "postgresql",
    "postgres":         "postgresql",
    "pg":               "postgresql",
    "sqlite":           "sqlite",
    "mongodb":          "mongodb",
    "mongo":            "mongodb",
    "redis":            "redis",
    # Cloud
    "aws":              "aws",
    "amazon web services": "aws",
    "gcp":              "gcp",
    "google cloud":     "gcp",
    "azure":            "azure",
    # Containers / orchestration
    "docker":           "docker",
    "kubernetes":       "kubernetes",
    "k8s":              "kubernetes",
    # ML / data
    "machine learning": "machine learning",
    "ml":               "machine learning",
    "tensorflow":       "tensorflow",
    "tf":               "tensorflow",
    "pytorch":          "pytorch",
    "torch":            "pytorch",
    "scikit-learn":     "scikit-learn",
    "sklearn":          "scikit-learn",
    # IaC / DevOps
    "terraform":        "terraform",
    "ansible":          "ansible",
    "ci/cd":            "ci/cd",
    "cicd":             "ci/cd",
    # APIs
    "rest":             "rest apis",
    "rest api":         "rest apis",
    "rest apis":        "rest apis",
    "grpc":             "grpc",
    # Go
    "go":               "go",
    "golang":           "go",
    # Java
    "java":             "java",
    # C / C++
    "c++":              "c++",
    "cpp":              "c++",
    "c":                "c",
    # Rust
    "rust":             "rust",
    # Git
    "git":              "git",
    "github":           "git",
    "gitlab":           "git",
}


def normalize_skill_name(raw: str | None) -> str | None:
    """
    Convert a raw skill name to a canonical lowercase name.

    Applies the synonym map first, then falls back to lowercased and stripped
    input if no synonym is found. Returns None for empty/whitespace input.

    Args:
        raw: Raw skill name (any casing, may have extra whitespace).

    Returns:
        Canonical skill name string, or None if the input is empty.

    Examples:
        "Python"           → "python"
        "K8S"              → "kubernetes"
        "Machine Learning" → "machine learning"
        "REST API"         → "rest apis"
        "  "               → None
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip().lower()
    # Look up in synonym map; fall back to the cleaned string itself
    return _SKILL_SYNONYMS.get(cleaned, cleaned)


# ---------------------------------------------------------------------------
# Country normalization (ISO-3166 alpha-2)
# ---------------------------------------------------------------------------

_COUNTRY_MAP: dict[str, str] = {
    # Full names
    "united states":         "US",
    "united states of america": "US",
    "usa":                   "US",
    "us":                    "US",
    "u.s.":                  "US",
    "u.s.a.":                "US",
    "india":                 "IN",
    "in":                    "IN",
    "united kingdom":        "GB",
    "uk":                    "GB",
    "great britain":         "GB",
    "gb":                    "GB",
    "canada":                "CA",
    "ca":                    "CA",
    "australia":             "AU",
    "au":                    "AU",
    "germany":               "DE",
    "de":                    "DE",
    "france":                "FR",
    "fr":                    "FR",
    "singapore":             "SG",
    "sg":                    "SG",
    "netherlands":           "NL",
    "nl":                    "NL",
    "sweden":                "SE",
    "se":                    "SE",
    "brazil":                "BR",
    "br":                    "BR",
    "china":                 "CN",
    "cn":                    "CN",
    "japan":                 "JP",
    "jp":                    "JP",
    "south korea":           "KR",
    "korea":                 "KR",
    "kr":                    "KR",
    "israel":                "IL",
    "il":                    "IL",
    "ireland":               "IE",
    "ie":                    "IE",
    "switzerland":           "CH",
    "ch":                    "CH",
    "new zealand":           "NZ",
    "nz":                    "NZ",
    "mexico":                "MX",
    "mx":                    "MX",
    "spain":                 "ES",
    "es":                    "ES",
    "italy":                 "IT",
    "it":                    "IT",
    "poland":                "PL",
    "pl":                    "PL",
    "ukraine":               "UA",
    "ua":                    "UA",
    "romania":               "RO",
    "ro":                    "RO",
    "portugal":              "PT",
    "pt":                    "PT",
    "pakistan":              "PK",
    "pk":                    "PK",
    "nigeria":               "NG",
    "ng":                    "NG",
    "kenya":                 "KE",
    "ke":                    "KE",
    "uae":                   "AE",
    "united arab emirates":  "AE",
    "ae":                    "AE",
    "remote":                None,   # "remote" is not a country
}

# Valid ISO-3166 alpha-2 codes (2 uppercase letters)
_ISO_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")


def normalize_country(raw: str | None) -> str | None:
    """
    Normalize a country string to ISO-3166 alpha-2 format.

    Args:
        raw: Country name, abbreviation, or already-normalized code.

    Returns:
        ISO-3166 alpha-2 string (e.g. "US"), or None if unrecognized.

    Examples:
        "United States"  → "US"
        "US"             → "US"
        "usa"            → "US"
        "Remote"         → None
        "Narnia"         → None  (unknown — logged)
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip().lower()
    result = _COUNTRY_MAP.get(cleaned)

    if result is None and cleaned != "remote":
        # Check if it's already a valid alpha-2 code passed in uppercase
        upper = raw.strip().upper()
        if _ISO_ALPHA2_RE.match(upper) and upper in _COUNTRY_MAP.values():
            return upper
        logger.debug("Unrecognized country: %r — setting to None", raw)

    return result


# ---------------------------------------------------------------------------
# Dispatcher for projection-time re-normalization
# ---------------------------------------------------------------------------

# Maps the 'normalize' key in a projection config to the corresponding function.
# Phase 11 (projector) uses this to look up and call the right normalizer.
NORMALIZE_DISPATCH: dict[str, Any] = {
    "E164":       normalize_phone,
    "email":      normalize_email,
    "date":       normalize_date,
    "canonical":  normalize_skill_name,
    "country":    normalize_country,
    "national":   format_phone_national,
}


def get_normalizer(key: str):
    """
    Return the normalizer function for a given config normalize key.

    Args:
        key: Value of the 'normalize' field in a projection config entry
             (e.g. 'E164', 'canonical', 'date').

    Returns:
        Callable or None if key is not recognized.
    """
    fn = NORMALIZE_DISPATCH.get(key)
    if fn is None:
        logger.warning("Unknown normalize key %r — will not re-normalize", key)
    return fn
