# Task 5 — ATS-direct discovery (Momus B4)

## Files
- backend/app/discovery/ats/__init__.py, _http.py, greenhouse.py, lever.py, ashby.py, smartrecruiters.py
- internapply/discovery/ats/__init__.py + same 4 mirrors + _http.py
- tests/test_ats_discovery.py (5 tests)

## Design
- Shared helper _http.py: httpx.AsyncClient(timeout=30, Limits max_connections=20, max_keepalive=10, http2=False), tenacity retry only 429/502/503/504 + timeouts (never 401/403/404/422), parse Retry-After seconds or HTTP-date clamp 30 + jitter via wait_exponential_jitter(multiplier=0.5, max=30).
- Each ATS reads config/boards.json working_boards (no hardcoded slugs), implements async search(boards, location_filter, title_filter) with client-side regex filters (Bangalore|Remote|WFH, devops|sre|platform|backend|infra|cloud|kubernetes|docker|terraform).
- Greenhouse: GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true, BS get_text.
- Lever: GET api.lever.co/v0/postings/{slug}?mode=json&skip=0&limit=100, hasMore pagination.
- Ashby: GET api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true (flag verified).
- SmartRecruiters: GET api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=0, 200-empty ambiguous handled (empty without totalFound → dead).
- Hash: canonical_id/jd_hash/simhash via hash_utils, source_ats tag, cursor = max(updated_at or posted_date) fallback.
- 404/403 → skip [].

## Verification
- `pytest tests/test_ats_discovery.py -q` → 5 passed (parses, 429 retry, 404 skip, cursor fallback, schema contract)
- `grep includeCompensation ashby.py` OK
- `grep Retry-After ats/*.py` OK (shared + per-file comment)
- `python -c "from backend.app.discovery.ats.greenhouse import GreenhouseDiscovery"` OK, invalid slug → [] no crash, canonical_id 64 hex
- No linkedin/playwright/hardcoded 200 in prod code
