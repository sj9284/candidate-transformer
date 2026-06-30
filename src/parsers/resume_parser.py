"""
Phase 4 — Resume Parser
=======================
Extracts candidate data from a PDF resume using pdfminer.six for text
extraction and regex for field identification.

Design rules:
- Output: single dict tagged {"_source": filepath}
- NO normalization or validation here — raw values only
- Never crash on bad/missing/corrupt PDF; log and return {}
- Extraction is best-effort: unknown resume layouts yield None for that field
- years_experience computed by summing experience date ranges (best-effort)
- All limitations are documented in README

Extraction strategy:
  1. Extract full text via pdfminer.six
  2. Run a cascade of regex patterns over the full text
  3. Use section-header anchors (SKILLS, EXPERIENCE, EDUCATION) to
     isolate blocks before applying per-field patterns within them
"""

import logging
import os
import re
from datetime import date
from io import StringIO
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _extract_text(filepath: str) -> str | None:
    """
    Extract raw text from a PDF file using pdfminer.six.

    Returns:
        Extracted text string, or None on any error.
    """
    try:
        # Import here so a missing pdfminer install gives a clear error
        from pdfminer.high_level import extract_text as pdfminer_extract

        text = pdfminer_extract(filepath)
        if not text or not text.strip():
            logger.warning("PDF %s produced no extractable text", filepath)
            return None
        return text
    except Exception as err:           # noqa: BLE001
        logger.error("Failed to extract text from %s: %s", filepath, err)
        return None


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

# Matches standard email addresses
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Matches a wide variety of phone formats
_PHONE_RE = re.compile(
    r"(?:\+?1[\s\-.]?)?"            # optional country code
    r"(?:\(?\d{3}\)?[\s\-.]?)"      # area code
    r"\d{3}[\s\-.]?\d{4}",          # local number
)

# LinkedIn and GitHub profile URLs
_LINKEDIN_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/in/[\w\-]+/?",
    re.IGNORECASE,
)
_GITHUB_RE = re.compile(
    r"https?://(?:www\.)?github\.com/[\w\-]+/?",
    re.IGNORECASE,
)
_PORTFOLIO_RE = re.compile(
    r"https?://(?!(?:www\.)?(?:linkedin|github)\.com)[\w\-./]+",
    re.IGNORECASE,
)

# YYYY-MM date (as used in the resume we generated)
_DATE_RANGE_RE = re.compile(
    r"(\d{4}-\d{2})\s+to\s+(\d{4}-\d{2}|[Pp]resent)",
    re.IGNORECASE,
)

# Section header anchors — used to isolate blocks of text
_SECTION_RE = re.compile(
    r"^(SKILLS|EXPERIENCE|EDUCATION|CERTIFICATIONS|SUMMARY|OBJECTIVE|PROJECTS)",
    re.MULTILINE | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

def _split_sections(text: str) -> dict[str, str]:
    """
    Split resume text into named sections using header anchors.

    Returns a dict mapping section_name (uppercase) → section_text.
    A "HEADER" key holds the text before the first section.
    """
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))

    if not matches:
        sections["HEADER"] = text
        return sections

    # Text before the first section header
    sections["HEADER"] = text[: matches[0].start()].strip()

    for i, match in enumerate(matches):
        name = match.group(1).upper()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[name] = text[start:end].strip()

    return sections


# ---------------------------------------------------------------------------
# Field extractors — each operates on a specific section or the full text
# ---------------------------------------------------------------------------

def _extract_name(header: str) -> str | None:
    """
    Heuristic: the candidate name is the first non-empty line in the header.
    We exclude lines that look like contact info (contain @, +, http, |).
    """
    for line in header.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip lines that look like contact info
        if any(ch in line for ch in ("@", "http", "|", "+")):
            continue
        if re.search(r"\d{3}", line):   # phone-like digits
            continue
        # Must look like a name: 2-4 words, mostly letters
        words = line.split()
        if 2 <= len(words) <= 5 and all(re.match(r"[A-Za-z\-'.]+$", w) for w in words):
            return line
    return None


def _extract_emails(text: str) -> list[str]:
    return list(dict.fromkeys(_EMAIL_RE.findall(text)))  # deduplicated, order-preserving


def _extract_phones(text: str) -> list[str]:
    raw = _PHONE_RE.findall(text)
    # Deduplicate by stripping non-digits for comparison
    seen_digits: set[str] = set()
    result: list[str] = []
    for p in raw:
        digits = re.sub(r"\D", "", p)
        if digits not in seen_digits:
            seen_digits.add(digits)
            result.append(p.strip())
    return result


def _extract_links(text: str) -> dict[str, str | None]:
    linkedin   = _LINKEDIN_RE.search(text)
    github     = _GITHUB_RE.search(text)
    portfolio  = _PORTFOLIO_RE.search(text)
    return {
        "linkedin":  linkedin.group(0).rstrip("/") if linkedin else None,
        "github":    github.group(0).rstrip("/")   if github   else None,
        "portfolio": portfolio.group(0)             if portfolio else None,
    }


def _extract_headline(header: str) -> str | None:
    """
    Heuristic: headline is the first sentence-like line after the name/contact block.
    Must be >= 10 chars, not look like contact info.
    """
    past_contact = False
    for line in header.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip contact-looking lines
        if any(ch in line for ch in ("@", "http", "|", "+")):
            past_contact = True
            continue
        if re.search(r"\d{3}", line):
            past_contact = True
            continue
        if past_contact and len(line) >= 10:
            return line
    return None


def _extract_skills(skills_section: str) -> list[str]:
    """
    Split the skills section text into individual skill tokens.
    Handles comma-separated and newline-separated lists.
    """
    if not skills_section:
        return []
    # Flatten newlines into commas, then split
    flat = re.sub(r"[\n\r]+", ", ", skills_section)
    raw_skills = [s.strip() for s in re.split(r"[,;]+", flat)]
    return [s for s in raw_skills if s and len(s) > 1]


def _extract_experience(exp_section: str) -> list[dict[str, str | None]]:
    """
    Parse experience blocks.
    Heuristic: each block starts with a line containing a company name and title,
    followed by a date range line, followed by a summary paragraph.
    """
    if not exp_section:
        return []

    entries: list[dict[str, str | None]] = []
    lines = [l.strip() for l in exp_section.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        date_match = _DATE_RANGE_RE.search(lines[i])
        if date_match:
            # The line immediately before this should be the company/title line
            title_line = lines[i - 1] if i > 0 else None
            company, title = _split_company_title(title_line)

            start  = date_match.group(1)
            end_raw = date_match.group(2)
            end    = None if end_raw.lower() == "present" else end_raw

            # Collect summary lines after the date line (until next date or end)
            summary_lines = []
            j = i + 1
            while j < len(lines) and not _DATE_RANGE_RE.search(lines[j]):
                # Stop if next line looks like a new job title
                if j + 1 < len(lines) and _DATE_RANGE_RE.search(lines[j + 1]):
                    break
                summary_lines.append(lines[j])
                j += 1

            entries.append({
                "company": company,
                "title":   title,
                "start":   start,
                "end":     end,
                "summary": " ".join(summary_lines) if summary_lines else None,
            })
            i = j
        else:
            i += 1

    return entries


def _split_company_title(line: str | None) -> tuple[str | None, str | None]:
    """
    Split a 'Company - Title' line into (company, title).
    Handles delimiters: ' - ', ' | ', '—'.
    """
    if not line:
        return None, None
    for delim in (" - ", " | ", "—", " – "):
        if delim in line:
            parts = line.split(delim, 1)
            return parts[0].strip() or None, parts[1].strip() or None
    # No delimiter found — treat the whole line as company
    return line.strip() or None, None


def _extract_education(edu_section: str) -> list[dict[str, Any]]:
    """
    Parse education blocks.
    Heuristic: institution is first non-blank line; degree/field and year follow.
    """
    if not edu_section:
        return []

    entries: list[dict[str, Any]] = []
    lines = [l.strip() for l in edu_section.splitlines() if l.strip()]

    i = 0
    while i < len(lines):
        # Institution line — likely starts with a proper noun (capitalized)
        institution_line = lines[i]
        degree = field = None
        end_year = None

        # Look for a degree/year line directly after
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            # Try to extract year
            year_match = re.search(r"\b(19|20)\d{2}\b", next_line)
            if year_match:
                end_year = int(year_match.group(0))
                # Extract degree and field from the rest of the line
                degree_part = re.sub(r"\|.*$", "", next_line).strip()
                degree_part = re.sub(r"\b(19|20)\d{2}\b", "", degree_part).strip()
                # Split on common degree separators
                if "," in degree_part:
                    parts = degree_part.split(",", 1)
                    degree = parts[0].strip() or None
                    field  = parts[1].strip() or None
                elif degree_part:
                    # Try to detect degree prefix (B.S., M.S., etc.)
                    deg_match = re.match(
                        r"(B\.?S\.?|M\.?S\.?|Ph\.?D\.?|B\.?A\.?|M\.?A\.?|B\.?E\.?|M\.?E\.?)",
                        degree_part, re.IGNORECASE
                    )
                    if deg_match:
                        degree = deg_match.group(0)
                        field  = degree_part[deg_match.end():].strip() or None
                    else:
                        degree = degree_part or None
                i += 1  # consumed the degree/year line

        entries.append({
            "institution": institution_line or None,
            "degree":      degree,
            "field":       field,
            "end_year":    end_year,
        })
        i += 1

    return entries


def _compute_years_experience(experience: list[dict[str, str | None]]) -> float | None:
    """
    Sum the duration of all experience entries in years.
    Entries with end=None are treated as ending today.
    Returns None if no valid date ranges are found.
    """
    today = date.today()
    total_months = 0
    found_any = False

    for exp in experience:
        try:
            start_str = exp.get("start")
            end_str   = exp.get("end")
            if not start_str:
                continue

            sy, sm = map(int, start_str.split("-"))
            start_date = date(sy, sm, 1)

            if end_str:
                ey, em = map(int, end_str.split("-"))
                end_date = date(ey, em, 1)
            else:
                end_date = today

            months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
            if months > 0:
                total_months += months
                found_any = True
        except (ValueError, AttributeError):
            continue

    if not found_any:
        return None

    years = round(total_months / 12, 1)
    # Clamp to plausible range (matches schema validator)
    return min(max(years, 0.0), 60.0)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_resume(filepath: str) -> dict[str, Any]:
    """
    Extract candidate data from a PDF resume.

    Returns:
        A raw field dict tagged {"_source": filepath}.
        Returns {} (with only _source) on any file-level error.
        Never raises.

    Fields returned (all raw / un-normalized):
        full_name, emails, phones, linkedin, github, portfolio,
        headline, skills_raw, experience, education, years_experience
    """
    base_result: dict[str, Any] = {"_source": filepath}

    # --- File checks ---
    if not os.path.exists(filepath):
        logger.error("Resume file not found: %s — skipping source", filepath)
        return base_result

    if os.path.getsize(filepath) == 0:
        logger.warning("Resume file is empty: %s — skipping source", filepath)
        return base_result

    # --- Text extraction ---
    text = _extract_text(filepath)
    if not text:
        logger.warning("No text extracted from %s — returning empty result", filepath)
        return base_result

    logger.debug("Extracted %d characters from %s", len(text), filepath)

    # --- Section splitting ---
    sections = _split_sections(text)
    header   = sections.get("HEADER", "")

    # --- Field extraction ---
    emails     = _extract_emails(text)
    phones     = _extract_phones(text)
    links      = _extract_links(text)
    name       = _extract_name(header)
    headline   = _extract_headline(header)
    skills_raw = _extract_skills(sections.get("SKILLS", ""))
    experience = _extract_experience(sections.get("EXPERIENCE", ""))
    education  = _extract_education(sections.get("EDUCATION", ""))
    years_exp  = _compute_years_experience(experience)

    result: dict[str, Any] = {
        "_source":         filepath,
        "full_name":       name,
        "emails":          emails,
        "phones":          phones,
        "linkedin":        links["linkedin"],
        "github":          links["github"],
        "portfolio":       links["portfolio"],
        "headline":        headline,
        "skills_raw":      skills_raw,       # list[str] — normalizer will canonicalize
        "experience":      experience,       # list[dict]
        "education":       education,        # list[dict]
        "years_experience": years_exp,       # float | None — best-effort
    }

    logger.info(
        "Resume parser: name=%r, %d email(s), %d skill(s), %d experience(s), "
        "%d education(s), years_exp=%s  [%s]",
        name, len(emails), len(skills_raw), len(experience),
        len(education), years_exp, filepath,
    )

    return result
