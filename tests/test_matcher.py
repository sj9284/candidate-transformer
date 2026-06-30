from src.matcher import cluster_candidates

def test_cluster_candidates_exact_email():
    dicts = [
        {"_source": "a.csv", "emails": ["test@example.com"], "full_name": "John"},
        {"_source": "b.pdf", "emails": ["test@example.com"], "full_name": "Jonathan"},
    ]
    clusters = cluster_candidates(dicts)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2

def test_cluster_candidates_fuzzy_name_and_phone():
    dicts = [
        {"_source": "a.csv", "full_name": "Robert Smith", "phones": ["+14155550101"]},
        {"_source": "b.pdf", "full_name": "Rob Smith", "phones": ["+14155550101"]},
    ]
    clusters = cluster_candidates(dicts)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2

def test_cluster_candidates_fuzzy_name_without_phone_no_match():
    dicts = [
        {"_source": "a.csv", "full_name": "Robert Smith"},
        {"_source": "b.pdf", "full_name": "Rob Smith"},
    ]
    clusters = cluster_candidates(dicts)
    assert len(clusters) == 2 # Should not merge without phone overlap

def test_cluster_candidates_no_match():
    dicts = [
        {"_source": "a.csv", "emails": ["a@example.com"], "full_name": "Alice"},
        {"_source": "b.pdf", "emails": ["b@example.com"], "full_name": "Bob"},
    ]
    clusters = cluster_candidates(dicts)
    assert len(clusters) == 2

def test_cluster_candidates_empty():
    assert cluster_candidates([]) == []
