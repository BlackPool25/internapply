"""CLI command for resume tailoring.

Tailors the master resume to match a specific job description, with LLM
verification against hallucination.

Usage::

    internapply tailor "SDE Intern" "Google" --jd-file description.txt
    internapply tailor --job-id 42
    echo "<JD text>" | internapply tailor "SDE Intern" "Google"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from internapply.resume.tailor import ResumeTailor

# ---------------------------------------------------------------------------
# App & console
# ---------------------------------------------------------------------------

tailor_app = typer.Typer(
    name="tailor",
    help="Tailor resume to a specific job description",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_jd_text(jd_file: str | None) -> str:
    """Read job description text from a file or stdin.

    If *jd_file* is provided, reads from that file.  Otherwise reads from
    stdin (piped input).  If stdin is a TTY and no file is given, raises
    an error.
    """
    if jd_file:
        path = Path(jd_file)
        if not path.exists():
            console.print(f"[red]File not found: {jd_file}[/red]")
            raise typer.Exit(1)
        return path.read_text(encoding="utf-8")

    # Read from stdin (piped input)
    if sys.stdin.isatty():
        console.print(
            "[red]No job description provided.[/red]\n"
            "Provide it via [bold]--jd-file[/bold] or pipe it through stdin."
        )
        raise typer.Exit(1)

    return sys.stdin.read().strip()


def _load_json_file(filepath: str) -> dict[str, Any]:
    """Load a JSON file from the filesystem (sync helper)."""
    import json

    path = Path(filepath)
    if not path.exists():
        console.print(f"[red]Analysis file not found: {filepath}[/red]")
        raise typer.Exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


async def _load_job_from_db(job_id: int) -> dict[str, Any]:
    """Load a job listing from the database by its ID.

    Returns a dict with keys ``title``, ``company``, ``description``.
    """
    from sqlalchemy import select

    from internapply.config import get_config
    from internapply.database import ORMJobListing, get_session, init_db

    cfg = get_config()
    await init_db(cfg.DATABASE_PATH)

    async with get_session() as session:
        result = await session.execute(
            select(ORMJobListing).where(ORMJobListing.id == job_id)
        )
        row = result.scalar_one_or_none()

    if row is None:
        console.print(f"[red]Job with ID {job_id} not found in database.[/red]")
        raise typer.Exit(1)

    return {
        "title": row.title,
        "company": row.company,
        "description": row.description or "",
    }


async def _run_analysis(
    job_title: str,
    company: str,
    job_description: str,
    jd_analysis_path: str | None,
) -> Any:
    """Run or load JD analysis for the given description.

    If *jd_analysis_path* is provided, loads it from JSON.  Otherwise runs
    ``JDAnalyzer`` to produce the analysis on the fly.
    """
    from internapply.resume.analyzer import JDAnalysis, JDAnalyzer

    if jd_analysis_path:
        raw = _load_json_file(jd_analysis_path)
        return JDAnalysis(**raw)

    # Run analyzer on the fly
    from internapply.models import JobListing

    listing = JobListing(
        title=job_title,
        company=company,
        description=job_description,
        source="cli",
        url="",
    )

    analyzer = JDAnalyzer()
    analysis = await analyzer.analyze(listing)
    console.print(
        f"[dim]JD analysis complete — {len(analysis.required_skills)} required skills, "
        f"match score: {analysis.match_score}[/dim]"
    )
    return analysis


def _display_tailored(data: dict[str, Any]) -> None:
    """Display the tailored resume in the terminal using Rich formatting."""
    score = data.get("verifier_score")
    issues = data.get("verifier_issues", [])

    # ── Verifier banner ────────────────────────────────────────────────
    if score is not None:
        if score >= 100:
            style = "green"
            label = "PASSED"
        elif score >= 60:
            style = "yellow"
            label = "WARNING"
        else:
            style = "red"
            label = "LOW CONFIDENCE"
        console.print(
            Panel(
                f"Verifier Score: [bold {style}]{score}/100 ({label})[/bold {style}]",
                border_style=style,
            )
        )
        if issues:
            console.print("[dim]Verifier issues:[/dim]")
            for issue in issues:
                console.print(f"  [red]• {issue}[/red]")
        console.print()

    # ── Summary ─────────────────────────────────────────────────────────
    summary = data.get("summary", "")
    if summary:
        console.print(Panel(summary, title="Tailored Summary", box=box.ROUNDED))
        console.print()

    # ── Skills ──────────────────────────────────────────────────────────
    skills = data.get("skills_reordered", [])
    if skills:
        console.print("[bold]Reordered Skills[/bold]")
        console.print("─" * 60)
        for i, skill in enumerate(skills, start=1):
            console.print(f"  {i:2d}. {skill}")
        console.print()

    # ── Projects ────────────────────────────────────────────────────────
    projects = data.get("projects", [])
    if projects:
        console.print("[bold]Tailored Projects[/bold]")
        console.print("─" * 60)
        for proj in projects:
            name = proj.get("name", "?")
            url = proj.get("url", "")
            tech = proj.get("tech", "")

            header = f"[bold cyan]{name}[/bold cyan]"
            if url:
                header += f"  [dim]({url})[/dim]"
            console.print(header)
            if tech:
                console.print(f"  [dim]Tech:[/dim] {tech}")

            bullets = proj.get("bullets", [])
            for b in bullets:
                console.print(f"  • {b}")
            console.print()
        console.print()

    # ── Education ──────────────────────────────────────────────────────
    edu = data.get("education", [])
    if edu:
        table = Table(
            title="Education",
            box=box.SIMPLE_HEAD,
            title_justify="left",
        )
        table.add_column("Degree", style="cyan")
        table.add_column("Institution", style="green")
        table.add_column("CGPA", style="yellow")
        table.add_column("Expected", style="white")
        for e in edu:
            table.add_row(
                e.get("degree", ""),
                e.get("institution", ""),
                e.get("cgpa", ""),
                e.get("expected", ""),
            )
        console.print(table)
        console.print()

    # ── Save path ──────────────────────────────────────────────────────
    # Determine the save path from the data or the last saved location
    save_path = data.get("_save_path", "")
    if save_path:
        console.print(f"[dim]Saved to: {save_path}[/dim]")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@tailor_app.callback(invoke_without_command=True)
def tailor(
    job_title: str = typer.Argument(
        None,
        help="Job title to tailor for (not needed with --job-id)",
    ),
    company: str = typer.Argument(
        None,
        help="Company name (not needed with --job-id)",
    ),
    jd_file: str | None = typer.Option(
        None,
        "--jd-file",
        "-f",
        help="Path to a file containing the job description",
    ),
    jd_analysis_file: str | None = typer.Option(
        None,
        "--jd-analysis",
        "-a",
        help="Path to a pre-saved JD analysis JSON file",
    ),
    job_id: int | None = typer.Option(
        None,
        "--job-id",
        "-j",
        help="Load job (title, company, description) from database by ID",
    ),
    no_verify: bool = typer.Option(
        False,
        "--no-verify",
        help="Skip the verifier gate (single tailoring pass only)",
        show_default=True,
    ),
    max_retries: int = typer.Option(
        2,
        "--max-retries",
        "-r",
        help="Max verifier retries (only when --no-verify is not set)",
        show_default=True,
    ),
) -> None:
    """Tailor the master resume to a specific job description.

    Provide the job title and company as arguments, and the job description
    text via [bold]--jd-file[/bold] or stdin.

    \b
    Examples:
        # Pipe JD text directly
        echo "Looking for a Python intern..." | internapply tailor "SDE Intern" "Google"

        # Read JD from a file
        internapply tailor "Backend Intern" "Stripe" --jd-file description.txt

        # Tailor for a job already in the database
        internapply tailor --job-id 42

        # Use a pre-saved JD analysis (skips the analysis step)
        internapply tailor "SDE Intern" "Google" --jd-file desc.txt --jd-analysis analysis.json

        # Single pass without verification
        internapply tailor "SDE Intern" "Google" --jd-file desc.txt --no-verify
    """
    # ── Resolve inputs ─────────────────────────────────────────────────
    if job_id is not None:
        # Load from database
        try:
            job = asyncio.run(_load_job_from_db(job_id))
        except Exception as exc:
            console.print(f"[red]Failed to load job from database: {exc}[/red]")
            raise typer.Exit(1) from exc
        title = job["title"]
        comp = job["company"]
        description = job["description"]
        console.print(
            f"[dim]Loaded job #{job_id}: {title} @ {comp}[/dim]"
        )
    else:
        if not job_title or not company:
            console.print(
                "[red]Both <job-title> and <company> arguments are required "
                "(or use --job-id).[/red]"
            )
            raise typer.Exit(1)
        title = job_title
        comp = company
        description = _read_jd_text(jd_file)

    if not description:
        console.print("[red]Job description is empty.[/red]")
        raise typer.Exit(1)

    # ── Run / load JD analysis ─────────────────────────────────────────
    try:
        analysis = asyncio.run(
            _run_analysis(title, comp, description, jd_analysis_file)
        )
    except Exception as exc:
        console.print(f"[red]JD analysis failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    # ── Tailor ─────────────────────────────────────────────────────────
    tailor_instance = ResumeTailor()

    try:
        if no_verify:
            result = asyncio.run(
                tailor_instance.tailor(
                    job_title=title,
                    company=comp,
                    job_description=description,
                    jd_analysis=analysis,
                )
            )
        else:
            result = asyncio.run(
                tailor_instance.tailor_with_verification(
                    job_title=title,
                    company=comp,
                    job_description=description,
                    jd_analysis=analysis,
                    max_retries=max_retries,
                )
            )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except Exception as exc:
        console.print(f"[red]Tailoring failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    # ── Display ────────────────────────────────────────────────────────
    console.print()
    console.print(
        Panel.fit(
            f"[bold]Tailored Resume[/bold] — {title} @ {comp}",
            border_style="blue",
        )
    )
    console.print()

    _display_tailored(result)
