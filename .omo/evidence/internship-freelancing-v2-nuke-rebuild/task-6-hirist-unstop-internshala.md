# Task 6 — Hirist + Unstop + Internshala XHR

## Files
- backend/app/discovery/hirist.py (gladiator.hirist.tech POST, appId:hirist, Retry-After clamp 30, no jobseeker-api)
- backend/app/discovery/unstop.py (unstop.com/api/public/opportunity/search-result, opportunity=all&per_page=50&searchTerm=devops, no oppstatus)
- backend/app/discovery/internshala_xhr.py (internships/ajax XHR + BS4 fragment individual_internship, no _extract_card_data)
- Mirrors: internapply/discovery/hirist.py, unstop.py, internshala_xhr.py
- tests/test_hirist_unstop_internshala.py (5 tests)

## Verification
- grep gladiator ok, no jobseeker-api
- grep unstop.com/api/public ok, no api.unstop.com, no oppstatus
- grep X-Requested-With + fragment ok
- python -c imports + canonical_id 64 for all 3
- pytest 5 passed

## Notes
- Tenacity wait_exponential_jitter(initial=0.5,max=30)
- Hash via hash_utils canonical_id/jd_hash/simhash, source_ats tagged
- 429 → Retry-After clamp 30, 404 skip
