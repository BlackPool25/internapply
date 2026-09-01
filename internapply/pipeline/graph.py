"""LangGraph pipeline graph — truncated to discover→filter→save."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from internapply.pipeline.nodes import discover_jobs, filter_jobs, save_jobs
from internapply.pipeline.state import PipelineState


def create_pipeline() -> StateGraph:
    """Create truncated pipeline: discover → filter → save (3 nodes, MemorySaver)."""
    workflow = StateGraph(PipelineState)

    workflow.add_node("discover", discover_jobs)
    workflow.add_node("filter", filter_jobs)
    workflow.add_node("save", save_jobs)

    workflow.add_edge("discover", "filter")
    workflow.add_edge("filter", "save")
    workflow.add_edge("save", END)

    workflow.set_entry_point("discover")

    checkpointer = MemorySaver()
    compiled = workflow.compile(checkpointer=checkpointer)

    logger.debug("Pipeline graph compiled with {} nodes", len(workflow.nodes))
    return compiled


__all__ = ["create_pipeline"]
