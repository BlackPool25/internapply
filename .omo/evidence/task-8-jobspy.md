# Task 8 — JobSpy Naukri/Indeed + LinkedIn overflow 999 breaker + wreq-js fallback

## Files
- backend/app/discovery/jobspy_linkedin.py (new, 220 lines)
- internapply/discovery/jobspy_linkedin.py (mirror via cp)
- backend/app/discovery/jobspy.py (patched 185→191, proxy guard)
- tests/test_jobspy.py (3 tests)

## Design
- Class JobSpyLinkedInDiscovery.search(search_term, location, hours_old=24, results_wanted=20, country_indeed="India")
- Per-site sequential scrape_jobs(site_name=[site]) with 0.5s constant rate, hours_old=24 incremental, country_indeed passed
- 999 detection via "999" in msg or HTTPStatusError.status_code==999; handled as circuit breaker not tenacity (999 not in 429/502/503/504)
- _handle_999: Redis SETNX breaker:linkedin EX 60 (try redis.from_url, nx=True) + in-memory dict fallback, log "breaker:linkedin open 60s"
- _is_breaker_open checks expiry before linkedin call, skips entirely when open
- _fallback_wreq: if WREQ_SIDECAR_URL env set POST http://wreq:3000/linkedin/search else skip, graceful
- Partial results: 999 on linkedin still returns Naukri+Indeed (never raises)
- hash: canonical_id/jd_hash via hash_utils, source_ats=naukri|indeed|linkedin
- Free-only v1: JobSpyScraper.__init__ proxy_url now None by default, only wired if WREQ_SIDECAR_URL set, _check_proxy guarded, search logs direct connection
- Mirror: internapply/discovery/jobspy_linkedin.py identical copy

## Verification
- `grep -q "999" backend/app/discovery/jobspy_linkedin.py && grep -q "breaker" backend/app/discovery/jobspy_linkedin.py` → OK (see grep output)
- `python -c "from backend.app.discovery.jobspy_linkedin import JobSpyLinkedInDiscovery; ..."` → 3 jobs, canonical_id 64 hex ✓
- `pytest tests/test_jobspy.py -q` → 3 passed (linkedin_parses canonical_id 64, indeed_no_limit 20, 999_circuit_open breaker SETNX EX 60 naukri still runs, second call skips linkedin)
- `grep PROXY_URL backend/app/discovery/jobspy.py` → only guarded WREQ path, no socks5://localhost:8888 routing

## Must NOT
- No tenacity retry on 999, no paid fantastic-jobs/rexreus, no socks5 proxybroker routing for free path, no auto-submit Easy Apply
