from src.merger import merge_cluster

def test_merge_cluster_single():
    cluster = [
        {"_source": "resume.pdf", "full_name": "John Doe", "emails": ["j@e.com"]}
    ]
    merged = merge_cluster(cluster)
    assert merged["full_name"] == "John Doe"
    assert merged["emails"] == ["j@e.com"]
    assert "_merged_sources" in merged

def test_merge_cluster_conflict_resolution():
    cluster = [
        {
            "_source": "data.csv",
            "full_name": "Jonathan Doe",
            "emails": ["jon@example.com"],
            "years_experience": 5,
        },
        {
            "_source": "resume.pdf",
            "full_name": "John Doe",
            "emails": ["j@example.com"],
            "years_experience": 6,
        }
    ]
    merged = merge_cluster(cluster)
    # CSV wins for full_name
    assert merged["full_name"] == "Jonathan Doe"
    # Resume wins for years_experience
    assert merged["years_experience"] == 6
    # Lists are unioned
    assert set(merged["emails"]) == {"jon@example.com", "j@example.com"}
    assert "data.csv" in merged["_merged_sources"]
    assert "resume.pdf" in merged["_merged_sources"]

def test_merge_cluster_empty():
    assert merge_cluster([]) == {}
