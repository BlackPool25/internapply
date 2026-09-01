"""Pipeline state schema for InternApply — truncated to discover→filter→save."""

from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict


class PipelineState(TypedDict):
    """Truncated pipeline state: discover → filter → save (no LLM in batch)."""

    config: dict
    jobs: list[dict]
    job_listings: list[dict]
    raw_jobs_count: int
    filtered_jobs_count: int
    current_job_index: int
    current_job: dict | None
    master_resume: dict | None
    tailored_resume: dict | None
    verifier_report: dict | None
    cover_letter: str | None
    email_draft: str | None
    email_contacts: list[dict]
    humanization_score: float | None
    application_results: list[dict]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    run_id: str | None
    dry_run: bool
    stage: str
    _cursor_max_seen: str


def initial_state(
    config: dict | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
) -> PipelineState:
    return PipelineState(
        config=config or {},
        jobs=[],
        job_listings=[],
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
        _cursor_max_seen="",
    )


__all__ = ["PipelineState", "initial_state"]
