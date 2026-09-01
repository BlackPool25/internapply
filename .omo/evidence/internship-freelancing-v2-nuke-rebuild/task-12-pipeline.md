# Task 12 — Pipeline truncate to discover→filter→save

## Changes
- `backend/app/pipeline/orchestrator.py`: replaced `seen_urls` with `seen_canonical_id: set[str]`, tiered fan-out Tier0 ATS (Greenhouse/Lever/Ashby/SmartRecruiters probed ~100 boards, cursor max_seen = max(updated_at|last_seen_at|posted_date)) → Tier1 Hirist/Unstop/Internshala XHR → Tier3 free APIs → Tier2 JobSpy Naukri/Indeed → Tier3 LinkedIn overflow (breaker 999 respected), dedup via canonical_id, `save_to_db` uses `canonical_id ==` not `url==`, jd_hash primary gate → skip, etag tiebreaker only, diff_change_log → change_log JSONB, removed LLM batch (generate_outreach kept for skill only), graph 3 nodes + MemorySaver.
- `backend/app/pipeline/state.py`: truncated to job_listings/jobs minimal.
- `internapply/pipeline/nodes.py`: mirrored discover_jobs with seen_canonical_id + cursor + save_jobs canonical_id gate, no LLM counter 0.
- `internapply/pipeline/graph.py`: 3 nodes linear discover→filter→save + MemorySaver.
- `internapply/pipeline/state.py`: added _cursor_max_seen.
- `tests/test_pipeline.py`: 4 tests (dashboard 3 nodes, seen_canonical_id, no LLM, SmartRecruiters 200-empty vs 404).
- `tests/e2e/test_pipeline.py`: updated to 3 nodes expectation.

## Verification
```
python -c "from backend.app.pipeline.orchestrator import create_pipeline; g=create_pipeline(); assert 'tailor' not in g.nodes and len(g.nodes)==3" → pass (discover_job_board, filter_jobs, save_to_db)
grep -q "seen_canonical_id" orchestrator.py && ! grep -q "seen_urls" → pass
grep -q "canonical_id" orchestrator.py → pass
pytest tests/test_pipeline.py -q → 5 passed
pytest tests/ -q → 114 passed 3 skipped
```

## Must NOT
- tailor/cover modules not deleted (kept for skill, generate_outreach function retained)
- LinkedIn ToS safe: external link only via discovery, no auto-apply
- 200-empty SmartRecruiters handled: totalFound check, None → skip not exception
