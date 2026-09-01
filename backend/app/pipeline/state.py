"""Pipeline state schema — truncated to discover→filter→save."""

from __future__ import annotations

import copy
from typing import Any

from typing_extensions import TypedDict


class PipelineState(TypedDict):
    """Truncated pipeline state: discover → filter → save."""

    config: dict
    master_resume: dict | None
    job_listings: list[dict]
    # legacy alias for internapply mirror
    jobs: list[dict]
    errors: list[str]
    warnings: list[str]
    dry_run: bool
    stage: str
    _cursor_max_seen: str


def initial_state(
    config: dict | None = None,
    dry_run: bool = False,
) -> PipelineState:
    return PipelineState(
        config=config or {},
        master_resume=None,
        job_listings=[],
        jobs=[],
        errors=[],
        warnings=[],
        dry_run=dry_run,
        stage="init",
        _cursor_max_seen="",
    )


def state_copy(state: PipelineState, **overrides: Any) -> PipelineState:
    new = copy.copy(state)
    for key, value in overrides.items():
        new[key] = value  # type: ignore[literal-required]
    return new


__all__ = ["PipelineState", "initial_state", "state_copy"]
