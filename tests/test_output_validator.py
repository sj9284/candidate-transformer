from src.output_validator import validate_output

def test_validate_output_success():
    projected = {"name": "John Doe", "age": 30}
    config = {
        "fields": [
            {"path": "name", "type": "string", "required": True},
            {"path": "age", "type": "number"}
        ]
    }
    result = validate_output(projected, config)
    assert result.is_valid
    assert not result.violations
    assert not result.warnings

def test_validate_output_missing_required():
    projected = {"age": 30}
    config = {
        "fields": [
            {"path": "name", "type": "string", "required": True}
        ]
    }
    result = validate_output(projected, config)
    assert not result.is_valid
    assert len(result.violations) == 1
    assert "missing or null" in result.violations[0]

def test_validate_output_type_mismatch():
    projected = {"age": "thirty"}
    config = {
        "fields": [
            {"path": "age", "type": "number"}
        ]
    }
    result = validate_output(projected, config)
    assert result.is_valid # not required, so just a warning
    assert len(result.warnings) == 1
    assert "Type mismatch" in result.warnings[0]

def test_validate_output_required_type_mismatch():
    projected = {"age": "thirty"}
    config = {
        "fields": [
            {"path": "age", "type": "number", "required": True}
        ]
    }
    result = validate_output(projected, config)
    assert not result.is_valid # required, so it's a violation
    assert len(result.violations) == 1
    assert "Type mismatch" in result.violations[0]
