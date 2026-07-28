"""CLI commands for managing resume data.

All commands read/write ``profile/resume.json`` as the single source of truth.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from internapply.resume.parser import (
    get_resume_summary,
    load_resume_json,
    parse_from_js_script,
    save_resume_json,
)

# ---------------------------------------------------------------------------
# App & console
# ---------------------------------------------------------------------------

resume_app = typer.Typer(
    name="resume",
    help="Manage resume data (profile/resume.json)",
    no_args_is_help=True,
)
console = Console()

_DEFAULT_JS_PATH = Path("data/generate_resume_ai.js")
_DEFAULT_PROFILE_PATH = Path("profile/resume.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_json_path() -> Path:
    """Return the absolute ``profile/resume.json`` path."""
    return _DEFAULT_PROFILE_PATH.resolve()


def _resolve_js_path(js_path: str | None) -> Path:
    """Return the absolute JS file path, using the default or user-provided path."""
    if js_path:
        return Path(js_path).resolve()
    return _DEFAULT_JS_PATH.resolve()


def _require_resume() -> dict:
    """Load and return the resume JSON; exit with an error if missing."""
    data = load_resume_json(str(_resolve_json_path()))
    if data is None:
        console.print(
            "[red]No resume found at profile/resume.json.[/red]\n"
            "Run [bold]internapply resume init[/bold] to create one."
        )
        raise typer.Exit(1)
    return data


def _save(data: dict) -> str:
    """Save resume data and return the path string."""
    return save_resume_json(data, str(_resolve_json_path()))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@resume_app.command()
def init(
    js_file: str | None = typer.Argument(
        None,
        help="Path to generate_resume_ai.js (default: data/generate_resume_ai.js)",
        show_default=False,
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path (default: profile/resume.json)",
    ),
) -> None:
    """Parse the JS resume generator and save structured data.

    This is a one-time setup command. Subsequent updates should use
    ``internapply resume refresh`` to re-parse the JS file.
    """
    js_path = _resolve_js_path(js_file)

    if not js_path.exists():
        console.print(f"[red]File not found: {js_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Parsing: {js_path}[/dim]")

    try:
        data = parse_from_js_script(str(js_path))
    except Exception as exc:
        console.print(f"[red]Failed to parse JS file: {exc}[/red]")
        raise typer.Exit(1)

    out_path = _resolve_json_path() if output is None else Path(output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_resume_json(data, str(out_path))

    console.print(
        f"[green]✓[/green] Resume saved to [bold]{out_path}[/bold]\n"
        f"  Name: {data.get('name', '?')}\n"
        f"  Email: {data.get('email', '?')}\n"
        f"  Skills categories: {len(data.get('skills', {}))}\n"
        f"  Projects: {len(data.get('projects', []))}"
    )


@resume_app.command()
def show(
    plain: bool = typer.Option(
        False,
        "--plain",
        "-p",
        help="Use plain text output instead of Rich formatting",
    ),
) -> None:
    """Display the current resume summary."""
    data = _require_resume()

    if plain:
        console.print(get_resume_summary(data))
        return

    # ── Header ─────────────────────────────────────────────────────
    name = data.get("name", "N/A")
    location = data.get("location", "")
    email = data.get("email", "")
    phone = data.get("phone", "")
    contacts = " | ".join(filter(None, [location, email, phone]))

    console.print()
    console.print(Panel(f"[bold]{name}[/bold]", subtitle=contacts, box=box.ROUNDED))
    console.print()

    # ── Summary ────────────────────────────────────────────────────
    summary = data.get("summary", "")
    if summary:
        console.print(Panel(summary, title="Professional Summary", box=box.ROUNDED))
        console.print()

    # ── Education ──────────────────────────────────────────────────
    edu = data.get("education", [])
    if edu:
        table = Table(title="Education", box=box.SIMPLE_HEAD, title_justify="left")
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

    # ── Skills ─────────────────────────────────────────────────────
    skills = data.get("skills", {})
    if skills:
        table = Table(title="Technical Skills", box=box.SIMPLE_HEAD, title_justify="left")
        table.add_column("Category", style="cyan", no_wrap=True)
        table.add_column("Skills", style="white")
        for cat, val in skills.items():
            table.add_row(cat, val)
        console.print(table)
        console.print()

    # ── Projects ───────────────────────────────────────────────────
    projects = data.get("projects", [])
    if projects:
        console.print("[bold]Projects[/bold]")
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

            desc = proj.get("description", [])
            for d in desc:
                console.print(f"  • {d}")
            console.print()
        console.print()

    # ── Additional ─────────────────────────────────────────────────
    additional = data.get("additional", [])
    if additional:
        table = Table(title="Additional Information", box=box.SIMPLE_HEAD, title_justify="left")
        table.add_column("Item", style="cyan")
        table.add_column("Details", style="white")
        for item in additional:
            table.add_row(item.get("label", ""), item.get("value", ""))
        console.print(table)
        console.print()


@resume_app.command(name="add-skill")
def add_skill(
    skill: str = typer.Argument(
        ...,
        help='Category and skill in "CategoryName: SkillName" format, e.g. "Backend: FastAPI"',
    ),
) -> None:
    """Add a skill to the resume.

    The argument must be in the format [bold]\"CategoryName: SkillName\"[/bold].
    If the category already exists the skill is appended; otherwise a new
    category is created.
    """
    data = _require_resume()

    if ":" not in skill:
        console.print(
            "[red]Invalid format.[/red] Use [bold]\"Category: Skill\"[/bold], "
            'e.g. "Backend: FastAPI"'
        )
        raise typer.Exit(1)

    category, new_skill = skill.split(":", 1)
    category = category.strip()
    new_skill = new_skill.strip()

    if not category or not new_skill:
        console.print("[red]Both category and skill name are required.[/red]")
        raise typer.Exit(1)

    skills: dict = data.setdefault("skills", {})

    if category in skills:
        existing = skills[category]
        # Check if it's already there
        items = [s.strip() for s in existing.split(",")]
        if new_skill in items:
            console.print(
                f"[yellow]Skill '{new_skill}' already exists under '{category}'.[/yellow]"
            )
            raise typer.Exit(0)
        items.append(new_skill)
        skills[category] = ", ".join(items)
        msg = (
            f"[green]✓[/green] Added [bold]{new_skill}[/bold] to "
            f"[bold]{category}[/bold]"
        )
    else:
        skills[category] = new_skill
        msg = (
            f"[green]✓[/green] Created new category [bold]{category}[/bold] "
            f"with skill [bold]{new_skill}[/bold]"
        )

    _save(data)
    console.print(msg)


@resume_app.command(name="add-project")
def add_project(
    name: str = typer.Argument(..., help="Project name"),
    description: str | None = typer.Option(
        None,
        "--description",
        "-d",
        help="Semicolon-separated description bullet points",
    ),
    tech: str | None = typer.Option(
        None,
        "--tech",
        "-t",
        help="Technology stack string",
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        help="Project URL (GitHub or live link)",
    ),
) -> None:
    """Add a project to the resume.

    The [bold]--description[/bold] option accepts semicolon-separated
    bullet points.

    Example::

        internapply resume add-project "MyApp" \\
            --description "Built feature X;Integrated API Y" \\
            --tech "FastAPI, PostgreSQL" \\
            --url "https://github.com/user/myapp"
    """
    data = _require_resume()

    project: dict[str, object] = {"name": name}

    if description:
        project["description"] = [
            b.strip() for b in description.split(";") if b.strip()
        ]
    else:
        project["description"] = []

    if tech:
        project["tech"] = tech
    else:
        project["tech"] = ""

    if url:
        project["url"] = url
    else:
        project["url"] = ""

    projects: list = data.setdefault("projects", [])
    projects.append(project)

    _save(data)
    console.print(
        f"[green]✓[/green] Project [bold]{name}[/bold] added "
        f"({len(project['description'])} bullet points)"
    )


@resume_app.command()
def edit() -> None:
    """Open the resume JSON in the system editor.

    Uses the ``EDITOR`` environment variable (defaults to ``vi`` on Linux,
    ``notepad`` on Windows).
    """
    json_path = _resolve_json_path()
    if not json_path.exists():
        console.print(
            f"[red]No resume found at {json_path}.[/red]\n"
            "Run [bold]internapply resume init[/bold] to create one first."
        )
        raise typer.Exit(1)

    editor = os.environ.get("EDITOR")
    if not editor:
        if sys.platform == "win32":
            editor = "notepad"
        else:
            editor = "vi"

    try:
        subprocess.run([editor, str(json_path)], check=True)
    except FileNotFoundError:
        console.print(
            f"[red]Editor '{editor}' not found.[/red]\n"
            "Set the [bold]EDITOR[/bold] environment variable to your editor of choice."
        )
        raise typer.Exit(1)
    except subprocess.CalledProcessError:
        console.print("[red]Editor exited with an error.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Saved changes to {json_path}")


@resume_app.command()
def refresh(
    js_file: str | None = typer.Argument(
        None,
        help="Path to generate_resume_ai.js (default: data/generate_resume_ai.js)",
        show_default=False,
    ),
) -> None:
    """Re-parse the JS generator file and update profile/resume.json.

    Useful after updating the original JS file with new information.
    """
    js_path = _resolve_js_path(js_file)

    if not js_path.exists():
        console.print(f"[red]File not found: {js_path}[/red]")
        raise typer.Exit(1)

    json_path = _resolve_json_path()
    if not json_path.exists():
        console.print(
            f"[yellow]No existing resume at {json_path} — running init instead.[/yellow]"
        )
        # Delegate to init
        init(js_file=js_file)
        return

    console.print(f"[dim]Re-parsing: {js_path}[/dim]")

    try:
        data = parse_from_js_script(str(js_path))
    except Exception as exc:
        console.print(f"[red]Failed to parse JS file: {exc}[/red]")
        raise typer.Exit(1)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    save_resume_json(data, str(json_path))

    console.print(
        f"[green]✓[/green] Resume refreshed from JS file.\n"
        f"  Name: {data.get('name', '?')}\n"
        f"  Projects: {len(data.get('projects', []))}\n"
        f"  Skills categories: {len(data.get('skills', {}))}"
    )
