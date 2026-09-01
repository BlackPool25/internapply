"""Tests for truncated pipeline: 3 nodes, seen_canonical_id, no LLM, SmartRecruiters empty vs 404."""

from __future__ import annotations

import pytest

from internapply.pipeline.state import initial_state as intern_initial
from internapply.pipeline.graph import create_pipeline as intern_create
from internapply.pipeline.nodes import discover_jobs, filter_jobs


class TestDashboardOnly3Nodes:
    def test_dashboard_only_3_nodes(self):
        """Pipeline must have exactly 3 nodes, no tailor."""
        g = intern_create()
        user_nodes = {n for n in g.nodes if not n.startswith("__")}
        assert len(user_nodes) == 3, f"expected 3 nodes got {user_nodes}"
        assert "tailor" not in user_nodes
        assert user_nodes == {"discover", "filter", "save"}

    def test_backend_pipeline_3_nodes(self):
        from backend.app.pipeline.orchestrator import create_pipeline
        g = create_pipeline()
        # langgraph StateGraph nodes dict may have internal keys; filter __
        # Compiled graph nodes via .nodes or .get_graph().nodes
        try:
            nodes = set(g.nodes.keys())
        except Exception:
            nodes = set(g.get_graph().nodes.keys())
        user = {n for n in nodes if not n.startswith("__")}
        assert len(user) == 3, f"backend expected 3 nodes got {user}"
        assert "tailor" not in user


class TestSeenCanonicalId:
    @pytest.mark.asyncio
    async def test_seen_canonical_id_duplicate_skipped(self):
        """Second run duplicate canonical_id is skipped via seen_canonical_id dedup."""
        state = intern_initial(dry_run=False)
        # craft two jobs with same canonical_id
        from internapply.discovery.hash_utils import canonical_id
        cid = canonical_id("Acme", "DevOps Intern", "Bangalore", "https://example.com/1")
        jobs = [
            {"title": "DevOps Intern", "company": "Acme", "location": "Bangalore", "url": "https://example.com/1", "canonical_id": cid, "jd_hash": "a"*64, "description": "d1"},
            {"title": "DevOps Intern", "company": "Acme", "location": "Bangalore", "url": "https://example.com/1", "canonical_id": cid, "jd_hash": "a"*64, "description": "d1"},
        ]
        state["jobs"] = jobs
        state["job_listings"] = jobs
        result = await filter_jobs(state)
        filtered = result.get("jobs") or result.get("job_listings") or []
        assert len(filtered) == 1, f"duplicate canonical_id should be deduped to 1, got {len(filtered)}"


class TestNoLLMInBatch:
    @pytest.mark.asyncio
    async def test_no_llm_in_batch(self):
        """Dry-run discover→filter must not call LLM (counter 0)."""
        from internapply.pipeline.nodes import _get_llm_count, _reset_llm_count
        _reset_llm_count()
        g = intern_create()
        state = intern_initial(dry_run=True, run_id="test-no-llm")
        result = await g.ainvoke(state, config={"configurable": {"thread_id": "test-no-llm-1"}})
        assert _get_llm_count() == 0, f"LLM count should be 0 in dry-run, got {_get_llm_count()}"
        assert result.get("stage") == "save"


class TestSmartRecruitersEmptyVs404:
    @pytest.mark.asyncio
    async def test_smartrecruiters_empty_vs_404(self):
        """SmartRecruiters 200 empty handled not exception; 404 returns None via _http."""
        from unittest.mock import AsyncMock, patch
        import httpx
        from backend.app.discovery.ats.smartrecruiters import SmartRecruitersDiscovery

        # Case 1: 200 with empty content and totalFound 0 → returns [] not exception
        mock_client = AsyncMock()
        # mock fetch_json to return {"content": [], "totalFound": 0}
        with patch("backend.app.discovery.ats._http.fetch_json", new=AsyncMock(return_value={"content": [], "totalFound": 0})):
            disc = SmartRecruitersDiscovery()
            result = await disc.search(boards=[{"slug": "testco", "ats_type": "smartrecruiters"}])
            assert result == [], f"empty with totalFound 0 should return [] not exception, got {result}"

        # Case 2: 200 with empty dict (no content key) → treated as dead, returns []
        with patch("backend.app.discovery.ats._http.fetch_json", new=AsyncMock(return_value={})):
            disc = SmartRecruitersDiscovery()
            result = await disc.search(boards=[{"slug": "testco2", "ats_type": "smartrecruiters"}])
            assert result == []

        # Case 3: fetch_json returns None (404) → returns [] not exception
        with patch("backend.app.discovery.ats._http.fetch_json", new=AsyncMock(return_value=None)):
            disc = SmartRecruitersDiscovery()
            result = await disc.search(boards=[{"slug": "deadco", "ats_type": "smartrecruiters"}])
            assert result == []

        # Case 4: 200 with data → parses
        payload = {"content": [{"id": "1", "name": "DevOps Intern", "company": {"name": "Acme"}, "location": {"city": "Bangalore"}, "jobAd": {"sections": [{"text": "desc"}]}, "ref": "https://example.com/1"}]}
        with patch("backend.app.discovery.ats._http.fetch_json", new=AsyncMock(return_value=payload)):
            disc = SmartRecruitersDiscovery()
            result = await disc.search(boards=[{"slug": "acme", "ats_type": "smartrecruiters"}])
            assert len(result) == 1
            assert result[0]["canonical_id"]
            assert len(result[0]["canonical_id"]) == 64
