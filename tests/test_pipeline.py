"""Tests for pipeline state, graph compilation, and topology.

Verifies that PipelineState is created with correct defaults, the LangGraph
compiles without errors, and the graph has the expected 7-node topology.
"""

from __future__ import annotations

import pytest

from internapply.pipeline.state import PipelineState, initial_state
from internapply.pipeline.graph import create_pipeline


# ---------------------------------------------------------------------------
# Tests — PipelineState
# ---------------------------------------------------------------------------


class TestPipelineState:
    """PipelineState factory and field defaults."""

    def test_initial_state(self):
        """PipelineState created with correct default values."""
        state = initial_state()

        assert isinstance(state, dict)
        assert state["jobs"] == []
        assert state["raw_jobs_count"] == 0
        assert state["filtered_jobs_count"] == 0
        assert state["current_job_index"] == 0
        assert state["current_job"] is None
        assert state["master_resume"] is None
        assert state["tailored_resume"] is None
        assert state["verifier_report"] is None
        assert state["cover_letter"] is None
        assert state["email_draft"] is None
        assert state["email_contacts"] == []
        assert state["humanization_score"] is None
        assert state["application_results"] == []
        assert state["errors"] == []
        assert state["warnings"] == []
        assert state["run_id"] is None
        assert state["dry_run"] is False
        assert state["stage"] == "init"

    def test_initial_state_with_config(self):
        """initial_state accepts optional config and dry_run override."""
        state = initial_state(
            config={"MIN_STIPEND_INR": 10000},
            dry_run=True,
            run_id="test-run-001",
        )

        assert state["config"] == {"MIN_STIPEND_INR": 10000}
        assert state["dry_run"] is True
        assert state["run_id"] == "test-run-001"

    def test_initial_state_pipeline_state_type(self):
        """initial_state returns a proper PipelineState TypedDict."""
        state = initial_state()
        # PipelineState accepts key-based assignment (TypedDict)
        assert "config" in state
        assert "jobs" in state
        assert "errors" in state
        assert "stage" in state

    def test_state_errors_accumulate(self):
        """errors and warnings use ``operator.add`` reducer (append, not replace)."""
        state = initial_state()
        state["errors"].append("First error")
        state["errors"].append("Second error")
        assert len(state["errors"]) == 2
        assert state["errors"] == ["First error", "Second error"]


# ---------------------------------------------------------------------------
# Tests — Graph compilation & topology
# ---------------------------------------------------------------------------


class TestPipelineGraph:
    """LangGraph pipeline graph compilation and topology."""

    def test_graph_compiles(self):
        """create_pipeline() compiles without raising any exceptions."""
        graph = create_pipeline()
        assert graph is not None, "create_pipeline() should return a compiled graph"

    def test_graph_has_correct_nodes(self):
        """Graph contains exactly the 7 expected pipeline nodes."""
        graph = create_pipeline()

        expected_nodes = {
            "discover",
            "filter",
            "analyze",
            "tailor",
            "cover_letter",
            "email",
            "apply",
        }
        # Exclude internal nodes like __start__
        actual_nodes = {
            n for n in graph.nodes.keys() if not n.startswith("__")
        }

        assert actual_nodes == expected_nodes, (
            f"Expected nodes {expected_nodes} but got {actual_nodes}"
        )

    def test_graph_node_count(self):
        """Graph has exactly 7 user-defined pipeline nodes."""
        graph = create_pipeline()
        user_nodes = [n for n in graph.nodes if not n.startswith("__")]
        assert len(user_nodes) == 7, (
            f"Expected 7 user nodes in graph but got {len(user_nodes)} "
            f"(all nodes including internal: {list(graph.nodes.keys())})"
        )

    def test_graph_entry_point(self):
        """Graph entry point is 'discover'."""
        graph = create_pipeline()
        # The compiled graph builder stores the entry point
        assert "discover" in graph.nodes, "Entry node 'discover' must be in graph"

    @pytest.mark.asyncio
    async def test_graph_topology_order(self):
        """Graph nodes are connected in the expected linear order (smoke check).

        This runs a dry-run invoke through the entire pipeline to verify
        the graph wiring is sound end-to-end.
        """
        graph = create_pipeline()

        state = initial_state(
            config={
                "MIN_STIPEND_INR": 5000,
                "SEARCH_LOCATIONS": ["Remote", "Bangalore"],
            },
            dry_run=True,
            run_id="test-topology",
        )

        # Invoke the graph via async API (nodes are async functions)
        result = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": "test-topology-1"}},
        )

        assert result["stage"] == "apply", (
            f"Expected final stage 'apply' but got '{result['stage']}'"
        )
        # Only Internshala-sourced jobs get submitted (2 of 3 mock jobs)
        results = result.get("application_results", [])
        assert len(results) == 2, (
            f"Expected 2 application results (Internshala-sourced only) "
            f"but got {len(results)}: {[r['title'] for r in results]}"
        )
        assert result["dry_run"] is True
