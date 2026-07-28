"""Pipeline state schema for InternApply.

Defines the :class:`PipelineState` TypedDict used by the LangGraph state
graph to carry data between pipeline nodes.  Fields marked with
``Annotated[list[str], operator.add]`` support LangGraph's built-in reducer
for accumulating values across node invocations.
"""

from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict


class PipelineState(TypedDict):
    """Complete pipeline state carried through the LangGraph.

    Every node function reads from and writes to this dict.  Fields are
    grouped by pipeline phase — discovery, tailoring, outreach, tracking.
    """

    # ── Configuration ──────────────────────────────────────────────────
    config: dict  # Snapshot of the current application config

    # ── Job discovery results ──────────────────────────────────────────
    jobs: list[dict]  # List of job listings (serialized JobListing dicts)
    raw_jobs_count: int  # Total jobs found before filtering
    filtered_jobs_count: int  # Jobs after post-filtering

    # ── Current job being processed ────────────────────────────────────
    current_job_index: int  # Index of the job currently being processed
    current_job: dict | None  # The current job listing (serialized)

    # ── Resume tailoring ───────────────────────────────────────────────
    master_resume: dict | None  # Loaded master resume data
    tailored_resume: dict | None  # Tailored resume output
    verifier_report: dict | None  # Verifier gate report

    # ── Cover letter ───────────────────────────────────────────────────
    cover_letter: str | None

    # ── Email outreach ─────────────────────────────────────────────────
    email_draft: str | None
    email_contacts: list[dict]
    humanization_score: float | None

    # ── Application tracking ──────────────────────────────────────────
    application_results: list[dict]  # Results of each application attempt

    # ── Pipeline control ───────────────────────────────────────────────
    errors: Annotated[list[str], operator.add]  # Accumulated errors
    warnings: Annotated[list[str], operator.add]  # Accumulated warnings
    run_id: str | None  # Unique run identifier
    dry_run: bool  # If True, simulate without real API calls
    stage: str  # Current pipeline stage name


# ── Factory helpers ─────────────────────────────────────────────────────


def initial_state(
    config: dict | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
) -> PipelineState:
    """Return a fresh :class:`PipelineState` with default / empty values.

    This is the standard entry-point for creating pipeline state — it
    ensures every field is present with a sensible default so that nodes
    do not need to guard against ``KeyError``.
    """
    return PipelineState(
        config=config or {},
        jobs=[],
        raw_jobs_count=0,
        filtered_jobs_count=0,
        current_job_index=0,
        current_job=None,
        master_resume=None,
        tailored_resume=None,
        verifier_report=None,
        cover_letter=None,
        email_draft=None,
        email_contacts=[],
        humanization_score=None,
        application_results=[],
        errors=[],
        warnings=[],
        run_id=run_id,
        dry_run=dry_run,
        stage="init",
    )


__all__ = [
    "PipelineState",
    "initial_state",
]
