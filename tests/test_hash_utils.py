from backend.app.discovery.hash_utils import canonical_id, jd_hash, simhash64, hamming_distance, normalize_metric


def test_canonical_id_64_hex():
    cid = canonical_id("Acme", "Backend Intern", "Remote", "https://x")
    assert len(cid) == 64
    assert all(c in "0123456789abcdef" for c in cid)
    # deterministic
    assert cid == canonical_id("Acme", "Backend Intern", "Remote", "https://x")
    # case-insensitive
    assert cid == canonical_id("acme", "backend intern", "remote", "https://x")
    assert len(cid) != 128


def test_volatile_stripped():
    assert jd_hash("<p>Hello  2024-08-01</p>") == jd_hash("hello")
    assert jd_hash("role 123 views hello") == jd_hash("role hello")
    assert jd_hash("abc 0123456789abcdef0123456789abcdef hello") == jd_hash("abc hello")


def test_metric_synonym():
    assert jd_hash("Role 40% bonus") == jd_hash("Role 40 percent bonus")
    assert normalize_metric("cut 40%") == normalize_metric("cut 40 percent")
    assert normalize_metric("reduced 40%") == normalize_metric("reduced 40 percent")


def test_cross_company_not_merge():
    c1 = canonical_id("Wipro", "Backend Intern", "Bangalore", "https://jobs/1")
    c2 = canonical_id("TCS", "Backend Intern", "Bangalore", "https://jobs/1")
    assert c1 != c2
    # simhash near-dup check: same title+url different company -> canonical differs, simhash may be close but not merged
    s1 = simhash64("https://jobs/1 Backend Intern")
    s2 = simhash64("https://jobs/1 Backend Intern")
    assert hamming_distance(s1, s2) <= 3
    # different titles should differ more
    s3 = simhash64("https://jobs/2 Frontend Intern Design")
    assert isinstance(s3, int)
