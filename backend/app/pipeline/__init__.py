"""LangGraph dual-track pipeline orchestrator for InternApply.

Provides the :class:`PipelineState` TypedDict and the :func:`create_pipeline`
factory that assembles the 8-node :class:`~langgraph.graph.StateGraph` for
coordinated discovery, research, people/contact finding, and outreach
generation.
"""

from backend.app.pipeline.orchestrator import create_pipeline
from backend.app.pipeline.state import PipelineState, initial_state, state_copy

__all__ = [
    "create_pipeline",
    "PipelineState",
    "initial_state",
    "state_copy",
]
