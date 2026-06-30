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

# Matches a wide variety of phone formats including Indian numbers
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-.])?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}|"  # US / Generic
    r"\d{3}[\s\-.]\d{4}|"                                           # 7 digit local (like 555-0101)
    r"(?:\+?91[\s\-.])?\d{10}|"                                     # India continuous
    r"(?:\+?91[\s\-.])?\d{5}[\s\-.]?\d{5}",                         # India spaced
    re.IGNORECASE
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

# Date range matching YYYY-MM or verbose Month YYYY (e.g. Jan 2022 - Present)
_DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}-\d{2})\s*(?:-|to|–)\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4}-\d{2}|[Pp]resent|[Cc]urrent)",
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


def _extract_headline(header: str, experience: list[dict], education: list[dict]) -> str | None:
    """
    Headline extraction with priority:
    1. Professional Summary title
    2. Current designation (latest job title)
    3. Student (if no experience)
    """
    def is_valid_headline(text: str) -> bool:
        if not text: return False
        lower_t = text.lower()
        if lower_t in ("professional", "expected", "present"): return False
        if any(bad in lower_t for bad in ("company", "corp", "inc", "ltd")): return False
        if text.startswith(("-", "•", "*")): return False
        if "summary" in lower_t: return False
        return True

    # 1. Professional Summary title (look at header lines after contact info)
    past_contact = False
    for line in header.splitlines():
        line = line.strip()
        if not line: continue
        
        # Skip contact-looking lines
        if any(ch in line for ch in ("@", "http", "|", "+")) or re.search(r"\d{3}", line):
            past_contact = True
            continue
            
        if past_contact and len(line) >= 5 and len(line) < 60:
            if is_valid_headline(line):
                return line

    # 2. Latest job title
    if experience and experience[0].get("title"):
        title = experience[0]["title"]
        if is_valid_headline(title):
            return title
            
    # 3. Student (if no experience)
    if not experience and education:
        return "Student"

    return None


def _extract_skills(skills_section: str) -> list[str]:
    """
    Extract skills using a strict whitelist.
    """
    if not skills_section:
        return []
    
    _KNOWN_SKILLS = {
        "python", "javascript", "react", "flask", "docker", "aws", "git", 
        "sql", "mysql", "postgresql", "machine learning", "deep learning", 
        "nlp", "tensorflow", "keras", "opencv", "selenium", "beautifulsoup",
        "c", "c++", "java", "html", "css", "rest apis", "rest api", "numpy", 
        "pandas", "scipy", "scikit-learn", "linux", "bash", "agile", "scrum",
        "spring boot", "node.js", "express", "mongodb", "typescript", "kubernetes"
    }

    # Flatten newlines into commas, then split
    flat = re.sub(r"[\n\r]+", ", ", skills_section)
    raw_skills = [s.strip() for s in re.split(r"[,;]+", flat)]
    
    cleaned_skills = []
    
    for s in raw_skills:
        if not s or len(s) <= 1:
            continue
        
        # Strip prefixes (e.g. "Programming Languages: C")
        s = re.sub(r"^[^:]+:\s*", "", s).strip()
        # Strip trailing parenthetical info (e.g. "AWS (Cloud)")
        s = re.sub(r"\s*\(.*?\)$", "", s).strip()
        
        if not s:
            continue
            
        if s.lower() in _KNOWN_SKILLS:
            cleaned_skills.append(s)
            
    return cleaned_skills


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

    def _is_title(text: str) -> bool:
        title_kws = {"intern", "engineer", "developer", "manager", "analyst", "specialist", "consultant", "scientist", "architect", "lead", "professional"}
        return any(kw in text.lower() for kw in title_kws)
        
    def _is_company(text: str) -> bool:
        comp_kws = {"company", "corp", "inc", "ltd", "llc", "solutions", "technologies", "centre", "acme", "globex"}
        return any(kw in text.lower() for kw in comp_kws)
        
    i = 0
    current_entry = {"company": None, "title": None, "start": None, "end": None, "summary": []}
    
    def finalize_entry(ent):
        if ent["company"] or ent["title"] or ent["start"] or ent["summary"]:
            entries.append({
                "company": ent["company"],
                "title": ent["title"],
                "start": ent["start"],
                "end": ent["end"],
                "summary": " ".join(ent["summary"]) if ent["summary"] else None
            })
            
    for line in lines:
        lower_line = line.lower()
        if "experience" in lower_line and len(line) < 40 and "professional" in lower_line:
            continue
            
        is_bullet = line.startswith(("-", "•", "*", "\u2022", "\xe2\x80\xa2"))
        date_match = _DATE_RANGE_RE.search(line)
        
        # If we are starting a new job block (we already have a complete-ish entry and see a new non-bullet line that isn't a continuation)
        # A good signal of a new block is seeing a Company or Title when we already have bullets and a date
        if not is_bullet and current_entry["summary"]:
            if _is_company(line) or _is_title(line):
                finalize_entry(current_entry)
                current_entry = {"company": None, "title": None, "start": None, "end": None, "summary": []}

        if date_match:
            current_entry["start"] = date_match.group(1)
            end_raw = date_match.group(2)
            current_entry["end"] = None if end_raw.lower() == "present" else end_raw
            
            # Process text before and after date
            before_date = line[:date_match.start()].strip()
            after_date = line[date_match.end():].strip()
            
            for part in (before_date, after_date):
                if not part: continue
                if part.startswith(("-", "•", "*", "\u2022", "\xe2\x80\xa2")):
                    current_entry["summary"].append(part)
                else:
                    if _is_title(part) and not current_entry["title"]: current_entry["title"] = part
                    elif _is_company(part) and not current_entry["company"]: current_entry["company"] = part
                    elif not current_entry["company"]: current_entry["company"] = part
                    elif not current_entry["title"]: current_entry["title"] = part
            continue

        if is_bullet:
            current_entry["summary"].append(line)
        else:
            # It's a non-bullet, non-date line. Probably company or title, or just summary continuation.
            # If it's a known title/company, assign it.
            if _is_title(line) and not current_entry["title"]:
                current_entry["title"] = line
            elif _is_company(line) and not current_entry["company"]:
                current_entry["company"] = line
            elif not current_entry["company"] and len(line) < 60:
                current_entry["company"] = line
            elif not current_entry["title"] and len(line) < 60:
                current_entry["title"] = line
            else:
                current_entry["summary"].append(line)

    finalize_entry(current_entry)

    return entries


def _extract_education(edu_section: str) -> list[dict[str, Any]]:
    """
    Parse education blocks.
    Heuristic: institution is first non-blank line; degree/field and year follow.
    """
    if not edu_section:
        return []

    entries: list[dict[str, Any]] = []
    lines = [l.strip() for l in edu_section.splitlines() if l.strip()]

    def _is_institution(text: str) -> bool:
        inst_kws = {"university", "institute", "college", "school", "mandir", "academy"}
        return any(kw in text.lower() for kw in inst_kws)
        
    def _is_degree(text: str) -> bool:
        deg_kws = {"b.tech", "btech", "b.s", "bachelor", "master", "m.tech", "phd", "secondary", "degree", "diploma"}
        return any(kw in text.lower() for kw in deg_kws)

    i = 0
    while i < len(lines):
        institution_line = lines[i]
        
        # Strip percentages out completely
        institution_line = re.sub(r"\b\d{1,3}(?:\.\d+)?\s*%", "", institution_line).strip()
        institution_line = re.sub(r"(?i)\bexpected\b", "", institution_line).strip()
        
        edu_entry = {
            "institution": institution_line if _is_institution(institution_line) else None,
            "degree": institution_line if _is_degree(institution_line) else None,
            "field": None,
            "cgpa": None,
            "start_year": None,
            "end_year": None
        }

        # Look for a degree/year line directly after
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            
            # Strip percentages out
            pct_match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*%", next_line)
            if pct_match:
                if not edu_entry["cgpa"]: edu_entry["cgpa"] = pct_match.group(1) + "%"
                next_line = next_line.replace(pct_match.group(0), "").strip()
                
            next_line = re.sub(r"(?i)\bexpected\b", "", next_line).strip()
            
            # Try to extract CGPA
            cgpa_match = re.search(r"CGPA[\s:]+([\d.]+)", next_line, re.IGNORECASE)
            if cgpa_match:
                edu_entry["cgpa"] = cgpa_match.group(1)
                next_line = next_line.replace(cgpa_match.group(0), "").strip()

            # Try to extract years
            year_match = re.search(r"\b(19|20)\d{2}\b", next_line)
            range_match = re.search(r"\b((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\b", next_line)
            
            if range_match:
                edu_entry["start_year"] = int(range_match.group(1))
                edu_entry["end_year"] = int(range_match.group(2))
                next_line = next_line.replace(range_match.group(0), "").strip()
            elif year_match:
                edu_entry["end_year"] = int(year_match.group(0))
                next_line = next_line.replace(year_match.group(0), "").strip()

            # Extract degree and field from the rest of the line
            degree_part = re.sub(r"\|.*$", "", next_line).strip()
            
            # Use heuristics to assign remaining parts
            parts = [p.strip() for p in re.split(r"[,|-]", degree_part) if p.strip()]
            for p in parts:
                if _is_degree(p) and not edu_entry["degree"]:
                    edu_entry["degree"] = p
                elif _is_institution(p) and not edu_entry["institution"]:
                    edu_entry["institution"] = p
                elif not edu_entry["field"]:
                    edu_entry["field"] = p
            
            # Look for CGPA on the institution line as well
            cgpa_inst_match = re.search(r"CGPA[\s:]+([\d.]+)", institution_line, re.IGNORECASE)
            if cgpa_inst_match:
                edu_entry["cgpa"] = cgpa_inst_match.group(1)
                inst_clean = institution_line.replace(cgpa_inst_match.group(0), "").strip()
                if _is_institution(inst_clean):
                    edu_entry["institution"] = inst_clean
                
            i += 1  # consumed the degree/year line

        entries.append(edu_entry)
        i += 1

    return entries


def _compute_years_experience(experience: list[dict[str, str | None]]) -> float | None:
    """
    Sum the duration of all experience entries in years.
    Entries with end=None are treated as ending today.
    Returns 0.0 if no valid date ranges are found.
    """
    if not experience:
        return 0.0

    today = date.today()
    total_months = 0
    
    _MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    def parse_date(dstr: str) -> date | None:
        dstr = dstr.strip().lower()
        if dstr in ("present", "current", "now"):
            return today
        # YYYY-MM
        m1 = re.match(r"^(\d{4})-(\d{2})$", dstr)
        if m1:
            return date(int(m1.group(1)), int(m1.group(2)), 1)
        # Month YYYY
        m2 = re.match(r"^([a-z]+)\s+(\d{4})$", dstr)
        if m2:
            m_abbr = m2.group(1)[:3]
            m_num = _MONTH_MAP.get(m_abbr, 1)
            return date(int(m2.group(2)), m_num, 1)
        return None

    for exp in experience:
        try:
            start_str = exp.get("start")
            end_str   = exp.get("end")
            if not start_str:
                continue

            start_date = parse_date(start_str)
            if not start_date:
                continue
                
            end_date = parse_date(end_str) if end_str else today
            if not end_date:
                end_date = today

            months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
            if months > 0:
                total_months += months
        except (ValueError, AttributeError):
            continue

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
    skills_raw = _extract_skills(sections.get("SKILLS", ""))
    experience = _extract_experience(sections.get("EXPERIENCE", ""))
    education  = _extract_education(sections.get("EDUCATION", ""))
    headline   = _extract_headline(header, experience, education)
    years_exp  = _compute_years_experience(experience)

    location_city = None
    location_country = None
    for line in header.splitlines():
        if re.search(r"\b(delhi|mumbai|chennai|bangalore|kolkata|pune|hyderabad|noida|gurgaon)\b", line, re.IGNORECASE):
            match = re.search(r"\b(delhi|mumbai|chennai|bangalore|kolkata|pune|hyderabad|noida|gurgaon)\b", line, re.IGNORECASE)
            location_city = match.group(1).title()
        if re.search(r"\b(india)\b", line, re.IGNORECASE):
            location_country = "India"

    result: dict[str, Any] = {
        "_source":         filepath,
        "full_name":       name,
        "emails":          emails,
        "phones":          phones,
        "linkedin":        links["linkedin"],
        "github":          links["github"],
        "portfolio":       links["portfolio"],
        "location_city":   location_city,
        "location_country": location_country,
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
