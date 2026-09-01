# Task 9 — Freelance lite: Freelancer RSS + Internshala Freelance XHR + Upwork webhook

## Files
- backend/app/discovery/freelance/__init__.py (new)
- backend/app/discovery/freelance/freelancer_rss.py (new, FreelancerRSSDiscovery.fetch/search)
- backend/app/discovery/freelance/internshala_freelance.py (new, InternshalaFreelanceDiscovery.search)
- backend/app/discovery/freelance/upwork_webhook.py (new, handle_upwork_webhook + FastAPI router)
- internapply/discovery/freelance/* (mirrors via cp)
- tests/test_freelance.py (3 tests)

## Design
- FreelancerRSSDiscovery: GET https://www.freelancer.com/rss.xml?keyword=<encoded> via httpx AsyncClient http2=False, XML via xml.etree, project_id from guid/link digits, canonical_id sha256(HASH_SALT+project_id) 64 hex, jd_hash title+budget, source_ats freelancer_rss, hourly poll comment for arq cron
- InternshalaFreelanceDiscovery: reuse XHR with FREELANCE_XHR_URL=https://internshala.com/freelance/ajax fallback internships/ajax?jobType=freelance, same XHR_HEADERS, _parse_fragment reuse + freelance /freelance/ url prefix fallback
- upwork_webhook: handle_upwork_webhook(payload) gated by VOLLNA_RSS_URL env (check os.getenv + both configs), returns None if not set, else maps title/budget/skills to job dict source_ats upwork_wrapper canonical 64; FastAPI router POST /webhooks/upwork optional; no hardcoded dead Upwork RSS (grep passes)

## Freelance policy (README snippet)
- Fiverr: passive — set once, no poll (gig listing is seller-pushed, not searchable RSS).
- Toptal/Turing: skipped — vetting gate (invite-only screening, no public API/RSS).
- Upwork: never blast at 0 reviews (7.45% win bottom 3.76% per gigradar.io); listener only via Vollna https://www.vollna.com/rss/... or tryvibeworker.com webhook if VOLLNA_RSS_URL set else skip. Direct scrape forbidden (10/s per IP, cache ≤24h TOS, RSS dead Aug 20 2024).

## Verification
- python -c mock fetch canonical_id 64: `python -c "from backend.app.discovery.freelance.freelancer_rss import FreelancerRSSDiscovery; ... print(len(...fetch...))"` → 1, canonical 64 hex
- grep VOLLNA_RSS_URL passes: `grep -q "VOLLNA_RSS_URL" backend/app/discovery/freelance/upwork_webhook.py` → pass
- grep dead url fails (absent): `grep -q "upwork.com/ab/feed/jobs/rss" backend/.../upwork_webhook.py` → no match (pass)
- pytest tests/test_freelance.py -q → 3 passed (freelancer_rss parses mock XML assert project_id→canonical 64, internshala_freelance_xhr mock fragment, upwork_rss_dead_handled)
