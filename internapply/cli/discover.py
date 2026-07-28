"""CLI command for job discovery.

Runs the discovery (+ optional filtering) stages of the pipeline and
prints a summary table.  Results can be saved to the database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from internapply.pipeline.nodes import discover_jobs, filter_jobs
from internapply.pipeline.state import initial_state

# ---------------------------------------------------------------------------
# App & console
# ---------------------------------------------------------------------------

discover_app = typer.Typer(
    name="discover",
    help="Discover internship listings from configured sources",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_table(jobs: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of job dicts."""
    table = Table(
        title="Discovered Internships",
        box=box.SIMPLE_HEAD,
        title_justify="left",
        show_lines=False,
    )
    table.add_column("#", style="dim", no_wrap=True)
    table.add_column("Title", style="cyan", no_wrap=False)
    table.add_column("Company", style="green")
    table.add_column("Location", style="white")
    table.add_column("Stipend", style="yellow")
    table.add_column("Source", style="blue")
    table.add_column("Paid", style="magenta")

    for i, job in enumerate(jobs, start=1):
        stipend_min = job.get("stipend_min") or 0
        stipend_max = job.get("stipend_max") or 0
        if stipend_min and stipend_max and stipend_min != stipend_max:
            stipend = f"₹{stipend_min:,}-{stipend_max:,}"
        elif stipend_min:
            stipend = f"₹{stipend_min:,}"
        else:
            stipend = job.get("stipend_raw", "N/A")

        table.add_row(
            str(i),
            job.get("title", "?"),
            job.get("company", "?"),
            job.get("location", "N/A"),
            stipend,
            job.get("source", "?"),
            "✅" if job.get("is_paid") else "❌",
        )

    return table


async def _run_discovery(
    keywords: list[str] | None,
    locations: list[str] | None,
    max_jobs: int,
    dry_run: bool,
    save: bool,
) -> list[dict[str, Any]]:
    """Execute the discovery pipeline, optionally save to DB, return jobs."""
    # Load config
    from internapply.config import get_config

    cfg = get_config()
    config_dict = {
        "SEARCH_KEYWORDS": keywords or cfg.SEARCH_KEYWORDS,
        "SEARCH_LOCATIONS": locations or cfg.SEARCH_LOCATIONS,
        "MIN_STIPEND_INR": cfg.MIN_STIPEND_INR,
        "MAX_APPLICATIONS_PER_DAY": cfg.MAX_APPLICATIONS_PER_DAY,
        "DATABASE_PATH": cfg.DATABASE_PATH,
    }

    # Build initial state (mutable dict so we can .update())
    state: dict[str, Any] = dict(
        initial_state(
            config=config_dict,
            dry_run=dry_run,
        )
    )

    # ── Stage 1: Discover ──────────────────────────────────────────
    console.print("[bold]Stage 1: Discovering jobs…[/bold]")
    state.update(await discover_jobs(state))
    if state.get("errors"):
        console.print(f"[red]Discovery errors: {state['errors']}[/red]")
        return []

    jobs: list[dict[str, Any]] = state.get("jobs", [])
    raw_count = state.get("raw_jobs_count", len(jobs))
    console.print(f"  Found [bold]{raw_count}[/bold] raw job(s)")

    # ── Stage 2: Filter ────────────────────────────────────────────
    console.print("[bold]Stage 2: Filtering jobs…[/bold]")
    state.update(await filter_jobs(state))
    if state.get("errors"):
        console.print(f"[red]Filter errors: {state['errors']}[/red]")
        return []

    filtered = state.get("jobs", jobs)
    filtered_count = state.get("filtered_jobs_count", len(filtered))
    console.print(
        f"  [bold]{filtered_count}[/bold] job(s) after filtering "
        f"(removed {raw_count - filtered_count})"
    )

    # Apply max_jobs limit
    if max_jobs > 0 and len(filtered) > max_jobs:
        filtered = filtered[:max_jobs]
        console.print(f"  Limited to first [bold]{max_jobs}[/bold] jobs")

    # ── Save to database (upsert with dedup) ──────────────────────
    if save and not dry_run:
        try:
            from internapply.database import get_session, init_db, upsert_job_listing
            from internapply.pipeline.nodes import _parse_relative_date

            await init_db(config_dict.get("DATABASE_PATH"))
            saved_count = 0
            async with get_session() as session:
                for job in filtered:
                    posted_at_date = _parse_relative_date(job.get("posted_at"))
                    await upsert_job_listing(session, job, posted_at_date_value=posted_at_date)
                    saved_count += 1
            console.print(
                f"  [green]Saved {saved_count} listing(s) to database[/green]"
            )
        except Exception as exc:
            console.print(f"[red]Failed to save to database: {exc}[/red]")
    elif save and dry_run:
        console.print("  [yellow]--dry-run: skipping database save[/yellow]")

    return filtered


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@discover_app.callback(invoke_without_command=True)
def discover(
    keywords: str | None = typer.Option(
        None,
        "--keywords",
        "-k",
        help="Comma-separated search keywords (overrides config)",
    ),
    locations: str | None = typer.Option(
        None,
        "--locations",
        "-l",
        help="Comma-separated target locations (overrides config)",
    ),
    max_jobs: int = typer.Option(
        50,
        "--max-jobs",
        "-m",
        help="Maximum jobs to return",
        show_default=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Simulate discovery without real API calls",
        show_default=True,
    ),
    save: bool = typer.Option(
        True,
        "--save/--no-save",
        help="Save results to the database",
        show_default=True,
    ),
) -> None:
    """Discover internship listings from configured sources.

    Runs the discovery and filtering stages of the pipeline, then prints
    a summary table of matching jobs.

    Examples::

        # Default discovery with config keywords/locations
        internapply discover

        # Override keywords and locations
        internapply discover --keywords "python,rust" --locations "Remote"

        # Dry run to test connectivity
        internapply discover --dry-run

        # Increase max results
        internapply discover --max-jobs 100
    """
    parsed_keywords: list[str] | None = (
        [k.strip() for k in keywords.split(",") if k.strip()]
        if keywords
        else None
    )
    parsed_locations: list[str] | None = (
        [l.strip() for l in locations.split(",") if l.strip()]
        if locations
        else None
    )

    try:
        jobs = asyncio.run(
            _run_discovery(parsed_keywords, parsed_locations, max_jobs, dry_run, save)
        )
    except Exception as exc:
        console.print(f"[red]Discovery failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    if not jobs:
        console.print("[yellow]No jobs found.[/yellow]")
        raise typer.Exit(0)

    # ── Print table ────────────────────────────────────────────────
    console.print()
    table = _build_table(jobs)
    console.print(table)
    console.print(f"\n[dim]Total: {len(jobs)} job(s)[/dim]")
