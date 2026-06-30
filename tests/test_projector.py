from src.projector import _resolve_path, project_profile
from src.canonical_schema import CandidateProfile

def test_resolve_path_simple():
    data = {"full_name": "John Doe", "location": {"city": "San Francisco"}}
    val, found = _resolve_path("full_name", data)
    assert val == "John Doe"
    assert found is True
    
    val, found = _resolve_path("location.city", data)
    assert val == "San Francisco"
    assert found is True

def test_resolve_path_list_index():
    data = {"emails": ["a@test.com", "b@test.com"]}
    val, found = _resolve_path("emails[0]", data)
    assert val == "a@test.com"
    assert found is True
    
    val, found = _resolve_path("emails[2]", data)
    assert val is None
    assert found is False

def test_resolve_path_list_map():
    data = {"skills": [{"name": "python", "confidence": 0.9}, {"name": "go", "confidence": 0.8}]}
    val, found = _resolve_path("skills[].name", data)
    assert val == ["python", "go"]
    assert found is True

def test_project_profile():
    profile = CandidateProfile(
        candidate_id="123",
        full_name="John Doe",
        emails=["a@b.com"],
        phones=["+14155550101"],
        skills=[],
        experience=[],
        education=[],
        provenance=[],
        overall_confidence=1.0,
    )
    config = {
        "fields": [
            {"path": "name", "from": "full_name", "type": "string"},
            {"path": "email", "from": "emails[0]", "type": "string"}
        ]
    }
    projected = project_profile(profile, config)
    assert projected["name"] == "John Doe"
    assert projected["email"] == "a@b.com"
    assert "overall_confidence" not in projected

def test_project_profile_missing_required_error():
    profile = CandidateProfile(
        candidate_id="123",
        full_name="John Doe",
        emails=[],
        phones=[],
        skills=[],
        experience=[],
        education=[],
        provenance=[],
        overall_confidence=1.0,
    )
    config = {
        "fields": [
            {"path": "email", "from": "emails[0]", "type": "string", "on_missing": "error"}
        ]
    }
    projected = project_profile(profile, config)
    assert projected is None
