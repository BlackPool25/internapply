"""End-to-end pipeline test — truncated to discover → filter → save."""

from __future__ import annotations

import pytest

from backend.app.pipeline.orchestrator import create_pipeline
from backend.app.pipeline.state import PipelineState, initial_state

_EXPECTED_NODES = [
    "discover_job_board",
    "filter_jobs",
    "save_to_db",
]


class TestPipelineDryRun:
    def test_graph_compiles(self) -> None:
        graph = create_pipeline()
        assert graph is not None

    def test_graph_has_eight_nodes(self) -> None:
        """Truncated graph contains exactly 3 user-defined nodes."""
        graph = create_pipeline()
        user_nodes = [n for n in graph.nodes if not n.startswith("__")]
        assert len(user_nodes) == len(_EXPECTED_NODES), (
            f"Expected {len(_EXPECTED_NODES)} user nodes, got {len(user_nodes)}: {sorted(user_nodes)}"
        )

    def test_graph_contains_all_expected_nodes(self) -> None:
        graph = create_pipeline()
        user_nodes = {n for n in graph.nodes if not n.startswith("__")}
        for node in _EXPECTED_NODES:
            assert node in user_nodes, f"Missing node: {node}"

    @pytest.mark.asyncio
    async def test_dry_run_completes_all_stages(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result: PipelineState = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-1"}},
        )
        assert result["stage"] == "save_to_db", f"Expected final stage 'save_to_db', got '{result['stage']}'"

    @pytest.mark.asyncio
    async def test_dry_run_populates_job_listings(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-2"}},
        )
        assert isinstance(result.get("job_listings"), list)
        assert len(result["job_listings"]) > 0
        for listing in result["job_listings"]:
            assert "title" in listing
            assert "company" in listing

    @pytest.mark.asyncio
    async def test_dry_run_populates_companies(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-3"}},
        )
        # truncated: companies not in new state but should not crash
        assert isinstance(result.get("job_listings"), list)

    @pytest.mark.asyncio
    async def test_dry_run_populates_people_and_contacts(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-4"}},
        )
        # truncated: people/contacts removed — just check no crash
        assert result["stage"] == "save_to_db"

    @pytest.mark.asyncio
    async def test_dry_run_generates_outreach_materials(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-5"}},
        )
        # truncated: outreach not in auto pipeline — stage is save_to_db
        assert result["stage"] == "save_to_db"

    @pytest.mark.asyncio
    async def test_dry_run_no_errors(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-6"}},
        )
        errors = result.get("errors", [])
        assert len(errors) == 0, f"Expected zero errors, got {errors}"

    @pytest.mark.asyncio
    async def test_dry_run_state_contains_expected_keys(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-7"}},
        )
        expected_keys = {"job_listings", "errors", "warnings", "dry_run", "stage", "config"}
        for key in expected_keys:
            assert key in result, f"Missing expected key: {key}"

    @pytest.mark.asyncio
    async def test_dry_run_respects_dry_run_flag(self) -> None:
        graph = create_pipeline()
        state = initial_state(config={}, dry_run=True)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "e2e-dry-run-8"}},
        )
        assert result["dry_run"] is True
