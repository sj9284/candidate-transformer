# conftest.py — shared pytest fixtures for the full test suite
import pytest
import sys
import os

# Ensure project root is on sys.path when running from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Reusable raw dicts (pre-validator, mimicking parser output) ──────────

@pytest.fixture
def raw_csv_clean():
    """Clean single-row dict as produced by the CSV parser."""
    return {
        "_source":          "recruiter.csv",
        "full_name":        "John Smith",
        "email":            "john.smith@email.com",
        "phone":            "+1-415-555-0101",
        "location_city":    "San Francisco",
        "location_country": "United States",
        "linkedin":         "https://linkedin.com/in/johnsmith",
        "github":           None,
        "skills_raw":       "Python, SQL, Docker",
        "years_experience": "5",
    }


@pytest.fixture
def raw_csv_garbage():
    """Row with invalid email, phone, and URL — simulates bad data."""
    return {
        "_source":          "recruiter.csv",
        "full_name":        "J0hn Smyth",
        "email":            "not-an-email",
        "phone":            "000-GARBAGE",
        "location_city":    None,
        "location_country": "Narnia",
        "linkedin":         "just-text-not-url",
        "skills_raw":       "",
        "years_experience": "abc",
    }


@pytest.fixture
def raw_resume():
    """Minimal resume dict as produced by parse_resume()."""
    return {
        "_source":        "resume.pdf",
        "full_name":      "John Smith",
        "emails":         ["john.smith@email.com"],
        "phones":         ["+1 (415) 555-0101"],
        "linkedin":       "https://linkedin.com/in/johnsmith",
        "github":         "https://github.com/johnsmith",
        "skills_raw":     ["Python", "Go", "K8S", "REST API"],
        "years_experience": 6.9,
        "experience": [
            {"company": "Acme", "title": "SWE", "start": "2021-03", "end": None},
        ],
        "education": [
            {"institution": "UC Berkeley", "degree": "B.S.", "field": "CS", "end_year": 2019},
        ],
    }


@pytest.fixture
def validated_john(raw_csv_clean):
    """Validated dict for the clean John Smith CSV row."""
    from src.validator import validate_dict
    return validate_dict(raw_csv_clean)


@pytest.fixture
def validated_resume(raw_resume):
    """Validated dict for the resume row."""
    from src.validator import validate_dict
    return validate_dict(raw_resume)


@pytest.fixture
def validated_garbage(raw_csv_garbage):
    """Validated dict for the garbage row."""
    from src.validator import validate_dict
    return validate_dict(raw_csv_garbage)


@pytest.fixture
def john_cluster(validated_john, validated_resume):
    """A 2-dict cluster: CSV row + resume (same person)."""
    return [validated_john, validated_resume]


@pytest.fixture
def john_merged(john_cluster):
    """Merged dict for John Smith."""
    from src.merger import merge_cluster
    return merge_cluster(john_cluster)


@pytest.fixture
def john_scored(john_merged):
    """Merged + confidence-scored dict for John Smith."""
    from src.confidence import score_merged_dict
    return score_merged_dict(john_merged)


@pytest.fixture
def john_profile(john_scored):
    """Canonical CandidateProfile for John Smith."""
    from src.profile_builder import build_profile
    p = build_profile(john_scored)
    assert p is not None, "Profile build failed in fixture"
    return p


@pytest.fixture
def full_profiles():
    """Full pipeline over the real input files — 3 profiles."""
    from src.parsers.csv_parser import parse_csv
    from src.parsers.resume_parser import parse_resume
    from src.validator import validate_all, validate_dict
    from src.matcher import cluster_candidates
    from src.merger import merge_all
    from src.confidence import score_merged_dict
    from src.profile_builder import build_all

    csv_rows   = validate_all(parse_csv("input/recruiter.csv"))
    resume_row = validate_dict(parse_resume("input/resume.pdf"))
    clusters   = cluster_candidates(csv_rows + [resume_row])
    merged     = merge_all(clusters)
    for m in merged:
        score_merged_dict(m)
    return build_all(merged)
