"""Main CLI entrypoint for InternApply.

Usage::

    internapply --help
    internapply resume init
    internapply discover --dry-run
    internapply run --dry-run
    internapply status
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer
from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from internapply.cli.discover import discover_app
from internapply.cli.email import email_app
from internapply.cli.resume import resume_app
from internapply.cli.tailor import tailor_app

# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="internapply",
    help="Automated internship application system",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)

console = Console()

# ---------------------------------------------------------------------------
# Register sub-command groups
# ---------------------------------------------------------------------------

app.add_typer(resume_app, name="resume", help="Manage resume data")
app.add_typer(discover_app, name="discover", help="Discover internship listings")
app.add_typer(tailor_app, name="tailor", help="Tailor resume to a job description")
app.add_typer(email_app, name="email", help="Manage Gmail sending, drafts, and approval gate")

# ---------------------------------------------------------------------------
# run  —  execute the full pipeline
# ---------------------------------------------------------------------------


@app.command()
def run(
    max_jobs: int = typer.Option(
        50,
        "--max-jobs",
        "-m",
        help="Maximum number of jobs to process",
        show_default=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Simulate the pipeline without real API calls",
        show_default=True,
    ),
    from_stage: str | None = typer.Option(
        None,
        "--from-stage",
        "-s",
        help="Resume from a specific stage (discover, filter, analyze, "
        "tailor, cover_letter, email, apply)",
    ),
) -> None:
    """Execute the full InternApply pipeline.

    Runs every stage sequentially: discover → filter → analyze → tailor →
    cover_letter → email → apply.  Progress is printed after each stage.

    Examples::

        # Full pipeline dry-run (uses mock data, no external calls)
        internapply run --dry-run

        # Real run with default config
        internapply run

        # Limit to 10 jobs
        internapply run --max-jobs 10

        # Resume from the tailor stage
        internapply run --from-stage tailor
    """
    from internapply.config import get_config
    from internapply.database import init_db
    from internapply.pipeline.graph import create_pipeline
    from internapply.pipeline.state import initial_state

    valid_stages = {
        "discover",
        "filter",
        "analyze",
        "tailor",
        "cover_letter",
        "email",
        "apply",
    }
    if from_stage and from_stage not in valid_stages:
        console.print(
            f"[red]Invalid --from-stage value: '{from_stage}'.[/red]\n"
            f"Valid options: {', '.join(sorted(valid_stages))}"
        )
        raise typer.Exit(1)

    console.print(Panel.fit("[bold]InternApply Pipeline[/bold]", border_style="blue"))
    console.print()

    # ── Initialise ─────────────────────────────────────────────────
    run_id = str(uuid.uuid4())[:8]
    cfg = get_config()

    config_dict = {
        "SEARCH_KEYWORDS": list(cfg.SEARCH_KEYWORDS),
        "SEARCH_LOCATIONS": list(cfg.SEARCH_LOCATIONS),
        "MIN_STIPEND_INR": cfg.MIN_STIPEND_INR,
        "MAX_APPLICATIONS_PER_DAY": cfg.MAX_APPLICATIONS_PER_DAY,
        "DATABASE_PATH": cfg.DATABASE_PATH,
        "NAUKRI_APIFY_TOKEN": cfg.NAUKRI_APIFY_TOKEN or "",
        "HUNTER_API_KEY": cfg.HUNTER_API_KEY or "",
    }

    # Init DB for real runs
    if not dry_run:
        try:
            asyncio.run(init_db(cfg.DATABASE_PATH))
            console.print("[dim]Database initialised[/dim]")
        except Exception as exc:
            console.print(f"[red]Database init failed: {exc}[/red]")
            raise typer.Exit(1) from exc

    # ── Build pipeline ─────────────────────────────────────────────
    try:
        graph = create_pipeline()
    except Exception as exc:
        console.print(f"[red]Failed to create pipeline graph: {exc}[/red]")
        raise typer.Exit(1) from exc

    # ── Initial state ──────────────────────────────────────────────
    state: dict[str, Any] = initial_state(
        config=config_dict,
        dry_run=dry_run,
        run_id=run_id,
    )

    # Load master resume (non-critical — pipeline continues without it)
    try:
        from internapply.resume.parser import load_resume_json

        resume_data = load_resume_json()
        if resume_data:
            state["master_resume"] = resume_data
            console.print(f"[dim]Loaded resume: {resume_data.get('name', '?')}[/dim]")
        else:
            console.print("[yellow]No master resume found — some features will be skipped[/yellow]")
    except Exception as exc:
        logger.debug("Could not load resume: {}", exc)

    # ── Skip ahead if --from-stage ─────────────────────────────────
    if from_stage:
        # Pre-populate the state to skip stages (checkpointing handles rest)
        state["stage"] = from_stage

        # If skipping discovery, we need jobs (can't run later stages without them)
        if from_stage != "discover" and not state.get("jobs"):
            console.print(
                "[yellow]Warning: skipping discovery but no jobs in state. "
                "Pipeline may produce no results.[/yellow]"
            )

    # ── Execute pipeline ──────────────────────────────────────────
    thread_id = f"run_{run_id}"
    run_config = {"configurable": {"thread_id": thread_id}}

    console.print(f"Run ID: [bold]{run_id}[/bold]  |  Dry-run: [bold]{dry_run}[/bold]")
    console.print()

    try:
        final_state = asyncio.run(
            graph.ainvoke(state, config=run_config)
        )
    except Exception as exc:
        console.print(f"[red]Pipeline execution failed: {exc}[/red]")
        logger.opt(exception=True).error("Pipeline execution error")
        raise typer.Exit(1) from exc

    # ── Summary ────────────────────────────────────────────────────
    console.print()
    console.print(Panel.fit("[bold]Pipeline Complete[/bold]", border_style="green"))

    summary_table = Table(box=box.SIMPLE_HEAD, show_header=False)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="white")

    summary_table.add_row("Run ID", run_id)
    summary_table.add_row("Raw jobs discovered", str(final_state.get("raw_jobs_count", 0)))
    summary_table.add_row("Filtered jobs", str(final_state.get("filtered_jobs_count", 0)))
    summary_table.add_row("Applications submitted", str(len(final_state.get("application_results", []))))
    summary_table.add_row("Errors", str(len(final_state.get("errors", []))))
    summary_table.add_row("Warnings", str(len(final_state.get("warnings", []))))
    summary_table.add_row("Final stage", final_state.get("stage", "?"))

    console.print(summary_table)

    if final_state.get("errors"):
        console.print()
        console.print("[bold red]Errors encountered:[/bold red]")
        for err in final_state["errors"]:
            console.print(f"  • {err}")

    console.print()


# ---------------------------------------------------------------------------
# status  —  pipeline status overview
# ---------------------------------------------------------------------------


@app.command()
def status() -> None:
    """Show pipeline statistics and database summary.

    Displays counts of discovered jobs, applications, resumes, and recent
    activity from the database.
    """
    from sqlalchemy import func, select

    from internapply.config import get_config
    from internapply.database import ORMApplication, ORMJobListing, ORMResume, get_session, init_db

    cfg = get_config()

    console.print(Panel.fit("[bold]Pipeline Status[/bold]", border_style="blue"))
    console.print()

    try:
        asyncio.run(init_db(cfg.DATABASE_PATH))
    except Exception as exc:
        console.print(f"[red]Could not open database: {exc}[/red]")
        raise typer.Exit(1) from exc

    async def _gather_stats() -> dict[str, Any]:
        stats: dict[str, Any] = {}
        async with get_session() as session:
            # Job listing counts
            total_jobs = await session.execute(select(func.count(ORMJobListing.id)))
            stats["total_jobs"] = total_jobs.scalar() or 0

            paid_jobs = await session.execute(
                select(func.count(ORMJobListing.id)).where(ORMJobListing.is_paid.is_(True))
            )
            stats["paid_jobs"] = paid_jobs.scalar() or 0

            # By source
            result = await session.execute(
                select(ORMJobListing.source, func.count(ORMJobListing.id))
                .group_by(ORMJobListing.source)
            )
            stats["by_source"] = dict(result.all())

            # Application stats
            total_apps = await session.execute(select(func.count(ORMApplication.id)))
            stats["total_applications"] = total_apps.scalar() or 0

            by_status = await session.execute(
                select(ORMApplication.status, func.count(ORMApplication.id))
                .group_by(ORMApplication.status)
            )
            stats["applications_by_status"] = dict(by_status.all())

            # Resume count
            total_resumes = await session.execute(select(func.count(ORMResume.id)))
            stats["total_resumes"] = total_resumes.scalar() or 0

        return stats

    try:
        stats = asyncio.run(_gather_stats())
    except Exception as exc:
        console.print(f"[red]Failed to gather stats: {exc}[/red]")
        raise typer.Exit(1) from exc

    # ── Display table ──────────────────────────────────────────────
    table = Table(box=box.SIMPLE_HEAD, title="Database Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="white", justify="right")

    table.add_row("Total job listings", str(stats.get("total_jobs", 0)))
    table.add_row("  Paid listings", str(stats.get("paid_jobs", 0)))
    for source, count in stats.get("by_source", {}).items():
        table.add_row(f"  Source: {source}", str(count))
    table.add_row("Total applications", str(stats.get("total_applications", 0)))
    for status_val, count in stats.get("applications_by_status", {}).items():
        table.add_row(f"  Status: {status_val}", str(count))
    table.add_row("Saved resumes", str(stats.get("total_resumes", 0)))

    console.print(table)

    # ── Config summary ─────────────────────────────────────────────
    console.print()
    config_table = Table(box=box.SIMPLE_HEAD, title="Active Configuration")
    config_table.add_column("Key", style="cyan")
    config_table.add_column("Value", style="white")

    config_table.add_row("Keywords", ", ".join(cfg.SEARCH_KEYWORDS))
    config_table.add_row("Locations", ", ".join(cfg.SEARCH_LOCATIONS))
    config_table.add_row("Min Stipend", f"₹{cfg.MIN_STIPEND_INR:,}")
    config_table.add_row("Max Apps/Day", str(cfg.MAX_APPLICATIONS_PER_DAY))
    config_table.add_row("Database", cfg.DATABASE_PATH)

    console.print(config_table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
