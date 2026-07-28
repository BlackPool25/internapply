"""System check / doctor command for InternApply."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from internapply.config import get_config

doctor_app = typer.Typer(name="doctor", help="Check system setup and requirements")
console = Console()


@doctor_app.callback(invoke_without_command=True)
def doctor() -> None:
    """Run all system checks and display a status report."""
    cfg = get_config()
    table = Table(title="InternApply — System Check")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Detail")

    # 1. Python version
    import sys
    py_ok = sys.version_info >= (3, 11)
    table.add_row(
        "Python version",
        "✅" if py_ok else "❌",
        f"{sys.version}" if py_ok else f"Need 3.11+, got {sys.version}",
    )

    # 2. OpenCode Go API key
    api_ok = bool(cfg.OPENCODE_GO_API_KEY)
    table.add_row(
        "OPENCODE_GO_API_KEY",
        "✅" if api_ok else "❌",
        "Set in .env" if api_ok else "Missing — required for LLM features",
    )

    # 3. Hunter.io API key
    hunter_ok = bool(cfg.HUNTER_API_KEY)
    table.add_row(
        "HUNTER_API_KEY",
        "✅" if hunter_ok else "⚠️  (optional)",
        "Set in .env" if hunter_ok else "Email outreach won't work",
    )

    # 4. Gmail config
    gmail_ok = bool(cfg.GMAIL_SENDER_EMAIL) and bool(cfg.GMAIL_CLIENT_SECRET_PATH)
    table.add_row(
        "Gmail API config",
        "✅" if gmail_ok else "⚠️  (optional)",
        "Ready" if gmail_ok else "Email sending won't work until configured",
    )

    # 5. Resume file
    resume_path = Path("profile/resume.json")
    resume_ok = resume_path.exists()
    table.add_row(
        "Resume file",
        "✅" if resume_ok else "⚠️  (optional)",
        "profile/resume.json found" if resume_ok else "Run 'internapply resume init'",
    )

    # 6. Playwright / Chrome
    pw_ok = shutil.which("playwright") or shutil.which("chromium") or shutil.which("google-chrome")
    table.add_row(
        "Browser available",
        "✅" if pw_ok else "⚠️  (optional)",
        "Chrome/Chromium found" if pw_ok else "Playwright auto-apply won't work — install Chrome or run 'playwright install chromium'",
    )

    # 7. Database
    db_path = Path(cfg.DATABASE_PATH)
    db_ok = db_path.exists()
    table.add_row(
        "Database",
        "✅" if db_ok else "⚠️  (first run)",
        f"{db_path}" if db_ok else "Will be created on first run",
    )

    # 8. .env file
    env_path = Path(".env")
    env_ok = env_path.exists()
    table.add_row(
        ".env file",
        "✅" if env_ok else "❌",
        "Found" if env_ok else "Missing — copy .env.example to .env",
    )

    # 9. Git repo
    git_ok = (Path(".git")).exists()
    table.add_row(
        "Git repository",
        "✅",
        "Initialized" if git_ok else "Not initialized",
    )

    console.print(table)
    console.print()
    table2 = Table(title="CLI Quick Reference")
    table2.add_column("Command", style="green")
    table2.add_column("Description")
    table2.add_row("internapply resume init", "Import your resume from JS generator")
    table2.add_row("internapply discover", "Find internship listings")
    table2.add_row("internapply run", "Run the full pipeline")
    table2.add_row("internapply email setup", "Configure Gmail sending")
    table2.add_row("internapply status", "Show pipeline dashboard")
    console.print(table2)

    if not api_ok:
        raise typer.Exit(1)

__all__ = ["doctor_app"]
