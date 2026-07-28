"""LangGraph pipeline graph for InternApply.

Defines the :func:`create_pipeline` factory that assembles the
:class:`~langgraph.graph.StateGraph` — a linear topology of pipeline nodes
with checkpointing for resumability.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from internapply.pipeline.nodes import (
    analyze_job,
    apply_to_job,
    discover_jobs,
    filter_jobs,
    generate_cover_letter,
    prepare_email,
    tailor_resume,
)
from internapply.pipeline.state import PipelineState


def create_pipeline() -> StateGraph:
    """Create and compile the main pipeline :class:`~langgraph.graph.StateGraph`.

    The pipeline is a linear sequence of stages:

        discover → filter → analyze → tailor → cover_letter → email → apply

    Each node is an async function that receives the current
    :class:`PipelineState` and returns a partial dict of updated fields.

    The compiled graph includes in-memory checkpointing via
    :class:`~langgraph.checkpoint.memory.MemorySaver` so that the pipeline
    can be resumed from the last completed stage in a future iteration.

    Returns
    -------
    A compiled :class:`~langgraph.graph.StateGraph` whose ``.invoke()``
    or ``.ainvoke()`` method runs the pipeline against a state dict.
    """
    workflow = StateGraph(PipelineState)

    # ── Register nodes ─────────────────────────────────────────────
    workflow.add_node("discover", discover_jobs)
    workflow.add_node("filter", filter_jobs)
    workflow.add_node("analyze", analyze_job)
    workflow.add_node("tailor", tailor_resume)
    workflow.add_node("cover_letter", generate_cover_letter)
    workflow.add_node("email", prepare_email)
    workflow.add_node("apply", apply_to_job)

    # ── Linear edges ───────────────────────────────────────────────
    workflow.add_edge("discover", "filter")
    workflow.add_edge("filter", "analyze")
    workflow.add_edge("analyze", "tailor")
    # Note: verifier-gate conditional edge will be added in Wave 2
    workflow.add_edge("tailor", "cover_letter")
    workflow.add_edge("cover_letter", "email")
    workflow.add_edge("email", "apply")
    workflow.add_edge("apply", END)

    # ── Entry point ────────────────────────────────────────────────
    workflow.set_entry_point("discover")

    # ── Compile with checkpointing ─────────────────────────────────
    checkpointer = MemorySaver()
    compiled = workflow.compile(checkpointer=checkpointer)

    logger.debug("Pipeline graph compiled with {} nodes", len(workflow.nodes))
    return compiled


__all__ = ["create_pipeline"]
