from src.normalizer import (
    normalize_phone,
    normalize_email,
    normalize_date,
    normalize_skill_name,
    normalize_country,
)

def test_normalize_phone():
    assert normalize_phone("+1-415-555-0101") == "+14155550101"
    assert normalize_phone("(415) 555-0101", "US") == "+14155550101"
    assert normalize_phone("+91 98765 43210") == "+919876543210"
    assert normalize_phone("555-INVALID") is None
    assert normalize_phone("") is None

def test_normalize_email():
    assert normalize_email("  John.Smith@Email.COM  ") == "john.smith@email.com"
    assert normalize_email("not-an-email") is None
    assert normalize_email(None) is None

def test_normalize_date():
    assert normalize_date("2021-03") == "2021-03"
    assert normalize_date("03/2021") == "2021-03"
    assert normalize_date("March 2021") == "2021-03"
    assert normalize_date("Mar 2021") == "2021-03"
    assert normalize_date("2019") == "2019-01"
    assert normalize_date("present") is None
    assert normalize_date("not a date") is None
    assert normalize_date("1899-01") is None # Out of range

def test_normalize_skill_name():
    assert normalize_skill_name("Python") == "python"
    assert normalize_skill_name("K8S") == "kubernetes"
    assert normalize_skill_name("Machine Learning") == "machine learning"
    assert normalize_skill_name("REST API") == "rest apis"
    assert normalize_skill_name("  ") is None

def test_normalize_country():
    assert normalize_country("United States") == "US"
    assert normalize_country("US") == "US"
    assert normalize_country("usa") == "US"
    assert normalize_country("Remote") is None
    assert normalize_country("Narnia") is None
    assert normalize_country("INDIA") == "IN"
