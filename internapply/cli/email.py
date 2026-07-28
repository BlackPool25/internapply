"""CLI commands for email management via the Gmail API.

All email sends require the ``--approve`` flag as a human-in-the-loop gate.
No email is ever sent without explicit approval.

Usage::

    # Set up OAuth2 authentication
    internapply email setup

    # List pending application emails
    internapply email list

    # Send an email for a specific job
    internapply email send --job-id 42 --approve

    # Send all pending emails
    internapply email send --all --approve

    # Preview a draft without sending
    internapply email draft --job-id 42

    # Check daily quota
    internapply email status
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from internapply.outreach.sender import GmailSender

# ---------------------------------------------------------------------------
# App & console
# ---------------------------------------------------------------------------

email_app = typer.Typer(
    name="email",
    help="Manage Gmail sending, drafts, and approval gate",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_sender() -> GmailSender:
    """Return a configured :class:`GmailSender` instance."""
    return GmailSender()


async def _load_application(job_id: int) -> dict[str, Any] | None:
    """Load an application from the database by its job ID.

    Returns the application as a plain dict, or ``None`` if not found.
    """
    from sqlalchemy import select

    from internapply.config import get_config
    from internapply.database import ORMApplication, get_session, init_db

    cfg = get_config()
    await init_db(cfg.DATABASE_PATH)

    async with get_session() as session:
        result = await session.execute(
            select(ORMApplication).where(ORMApplication.job_id == job_id),
        )
        row = result.scalar_one_or_none()

    if row is None:
        return None

    from internapply.models import application_to_model

    return application_to_model(row).model_dump()


async def _load_job(job_id: int) -> dict[str, Any] | None:
    """Load a job listing from the database by its ID.

    Returns the job as a plain dict, or ``None`` if not found.
    """
    from sqlalchemy import select

    from internapply.config import get_config
    from internapply.database import ORMJobListing, get_session, init_db

    cfg = get_config()
    await init_db(cfg.DATABASE_PATH)

    async with get_session() as session:
        result = await session.execute(
            select(ORMJobListing).where(ORMJobListing.id == job_id),
        )
        row = result.scalar_one_or_none()

    if row is None:
        return None

    from internapply.models import job_listing_to_model

    return job_listing_to_model(row).model_dump()


async def _list_pending_applications(
    session: Any,
) -> list[dict[str, Any]]:
    """Return applications that have contacts but email not yet sent.

    Each result is enriched with ``_job_title`` and ``_company`` keys
    from the associated job listing.
    """
    from sqlalchemy import select

    from internapply.database import ORMApplication
    from internapply.models import application_to_model

    result = await session.execute(
        select(ORMApplication)
        .where(ORMApplication.email_sent.is_(False))
        .where(ORMApplication.email_contacts_json.isnot(None))
        .order_by(ORMApplication.id),
    )

    enriched: list[dict[str, Any]] = []
    for row in result.scalars().all():
        app = application_to_model(row)
        data = app.model_dump()

        # Enrich with job info
        job = await _load_job(app.job_id)
        if job:
            data["_job_title"] = job.get("title", "?")
            data["_company"] = job.get("company", "?")
        else:
            data["_job_title"] = "?"
            data["_company"] = "?"

        enriched.append(data)

    return enriched


async def _update_email_sent(app_id: int) -> None:
    """Mark an application's ``email_sent`` flag as ``True`` in the DB."""
    from sqlalchemy import select

    from internapply.config import get_config
    from internapply.database import ORMApplication, get_session, init_db

    cfg = get_config()
    await init_db(cfg.DATABASE_PATH)

    async with get_session() as session:
        result = await session.execute(
            select(ORMApplication).where(ORMApplication.id == app_id),
        )
        row = result.scalar_one_or_none()
        if row is not None:
            row.email_sent = True
            row.email_sent_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            from loguru import logger

            logger.debug("Marked app {} as email_sent=True", app_id)


def _generate_email_body(
    company: str,
    job_title: str,
    recipient_name: str | None = None,
) -> str:
    """Generate a plain-text cold email body.

    This is a simple template used for CLI drafts and manual sends.
    The pipeline's dedicated email stage uses LLM-powered generation
    instead.
    """
    from internapply.config import get_config

    cfg = get_config()
    sender_email = cfg.GMAIL_SENDER_EMAIL or "[Your Email]"

    greeting = f"Dear {recipient_name}," if recipient_name else "Dear Hiring Team,"
    return (
        f"{greeting}\n\n"
        f"I am writing to express my strong interest in the {job_title} "
        f"position at {company}. As a software engineer with experience "
        f"building backend systems and a passion for creating impactful "
        f"solutions, I believe my skills align well with what you are "
        f"looking for.\n\n"
        f"I have attached my resume for your review and would welcome the "
        f"opportunity to discuss how I can contribute to the team at "
        f"{company}.\n\n"
        f"Thank you for your time and consideration.\n\n"
        f"Best regards,\n"
        f"{sender_email}"
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@email_app.command()
def setup() -> None:
    """Run the OAuth2 flow and test the Gmail API connection.

    Opens a browser window for Google account authorisation (``gmail.send``
    scope only).  After successful authentication, sends a diagnostic
    email to the configured sender address to confirm everything works.
    """
    console.print(Panel.fit("[bold]Gmail API Setup[/bold]", border_style="blue"))
    console.print()

    sender = _get_sender()

    # ── Authenticate ──────────────────────────────────────────────────────
    console.print(
        "[dim]Starting OAuth2 flow — a browser window will open...[/dim]"
    )
    success = asyncio.run(sender.authenticate())

    if not success:
        console.print(
            "[red]✗[/red] Authentication failed. Check your:\n"
            "  • [bold]GMAIL_CLIENT_SECRET_PATH[/bold] — points to a valid "
            "``client_secret.json``\n"
            "  • [bold]GMAIL_SENDER_EMAIL[/bold] — matches the Google "
            "account you authorised"
        )
        raise typer.Exit(1)

    console.print("[green]✓[/green] Authentication successful!")
    console.print()

    # ── Test connection ───────────────────────────────────────────────────
    console.print("[dim]Sending a diagnostic email...[/dim]")
    test_ok = asyncio.run(sender.validate_connection())

    if test_ok:
        console.print(
            f"[green]✓[/green] Diagnostic email sent to "
            f"[bold]{sender._sender_email}[/bold].\n"
            f"  Check your inbox to confirm delivery."
        )
    else:
        console.print(
            "[yellow]⚠[/yellow] Authentication succeeded but the diagnostic "
            "email failed.\n"
            "  Try running [bold]internapply email setup[/bold] again or "
            "check your token."
        )
        raise typer.Exit(1)

    console.print()
    console.print(
        "[green]✓[/green] Gmail sender is ready.\n"
        "  Use [bold]internapply email send --job-id <id> --approve[/bold] "
        "to start sending."
    )


@email_app.command(name="list")
def list_pending() -> None:
    """Show applications with email contacts that need sending approval.

    Lists every application that has one or more contacts but has not
    had an email sent yet.  This is the queue you approve via
    ``internapply email send``.
    """
    console.print(
        Panel.fit("[bold]Pending Email Approvals[/bold]", border_style="blue")
    )
    console.print()

    apps = asyncio.run(_list_pending_applications())

    if not apps:
        console.print("[yellow]No pending applications found.[/yellow]")
        console.print(
            "Applications with email contacts that have not yet been sent "
            "will appear here once discovered."
        )
        return

    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("App ID", style="cyan", justify="right")
    table.add_column("Job ID", style="white", justify="right")
    table.add_column("Company", style="green")
    table.add_column("Title", style="white")
    table.add_column("Primary Contact", style="yellow")
    table.add_column("Status", style="magenta")

    for app in apps:
        contacts = app.get("email_contacts", [])
        contact_str = (
            contacts[0].get("email", "?") if contacts else "—"
        )
        table.add_row(
            str(app.get("id", "?")),
            str(app.get("job_id", "?")),
            app.get("_company", "?"),
            app.get("_job_title", "?"),
            contact_str,
            app.get("status", "?"),
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]Use [bold]internapply email send --job-id <id> --approve[/bold] "
        "to send an individual email.\n"
        "Use [bold]internapply email send --all --approve[/bold] to send "
        "all pending.[/dim]"
    )


@email_app.command()
def send(
    job_id: int | None = typer.Option(
        None,
        "--job-id",
        "-j",
        help="Send email for a specific job/application ID",
    ),
    all_pending: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Send emails for all pending applications",
    ),
    approve: bool = typer.Option(
        False,
        "--approve",
        help="[bold]REQUIRED[/bold] Confirm approval gate — no email is "
        "sent without this flag",
    ),
) -> None:
    """Send email(s) for job applications.

    The [bold]--approve[/bold] flag is **mandatory**.  This is the
    human-in-the-loop safety gate — no email is ever dispatched without
    it.

    \b
    Examples:

        # Send a single email
        internapply email send --job-id 42 --approve

        # Send all queued emails
        internapply email send --all --approve
    """
    # ── Approval gate ─────────────────────────────────────────────────────
    if not approve:
        console.print(
            "[red]✗[/red] The [bold]--approve[/bold] flag is required "
            "to send emails.\n"
            "  This is a safety gate to prevent accidental sends. "
            "Add it when you are ready."
        )
        raise typer.Exit(1)

    if not job_id and not all_pending:
        console.print(
            "[red]✗[/red] Specify either [bold]--job-id <id>[/bold] "
            "or [bold]--all[/bold]."
        )
        raise typer.Exit(1)

    if job_id and all_pending:
        console.print(
            "[red]✗[/red] Cannot use both [bold]--job-id[/bold] "
            "and [bold]--all[/bold] together."
        )
        raise typer.Exit(1)

    sender = _get_sender()

    # ── Check remaining quota ─────────────────────────────────────────────
    remaining = sender.get_remaining_quota()
    if remaining <= 0:
        console.print(
            "[red]✗[/red] Daily send limit (20) has been reached. "
            "Try again tomorrow."
        )
        raise typer.Exit(1)

    # ── Gather targets ────────────────────────────────────────────────────
    targets: list[dict[str, Any]] = []

    if job_id:
        app = asyncio.run(_load_application(job_id))
        if app is None:
            console.print(
                f"[red]✗[/red] No application found for job ID {job_id}."
            )
            raise typer.Exit(1)

        contacts = app.get("email_contacts", [])
        if not contacts:
            console.print(
                f"[red]✗[/red] Application for job {job_id} has no "
                "email contacts."
            )
            raise typer.Exit(1)

        job = asyncio.run(_load_job(app["job_id"]))
        targets.append({
            "app": app,
            "job": job or {},
            "contacts": contacts,
        })
    else:
        pending = asyncio.run(_list_pending_applications())
        if not pending:
            console.print("[yellow]No pending applications to send.[/yellow]")
            raise typer.Exit(0)

        # Respect quota: only take as many as we can send
        if len(pending) > remaining:
            console.print(
                f"[yellow]Only {remaining} of {len(pending)} pending "
                f"applications can be sent today (quota: {remaining}).[/yellow]"
            )
            pending = pending[:remaining]

        for app_item in pending:
            job = asyncio.run(_load_job(app_item["job_id"]))
            targets.append({
                "app": app_item,
                "job": job or {},
                "contacts": app_item.get("email_contacts", []),
            })

    # ── Confirm with user ─────────────────────────────────────────────────
    console.print(f"[bold]Ready to send {len(targets)} email(s)[/bold]")
    console.print(f"  Quota remaining: {remaining}")
    console.print()

    for t in targets:
        job_info = t["job"]
        company = job_info.get("company", "?")
        title = job_info.get("title", "?")
        contacts = t["contacts"]
        first_contact = contacts[0].get("email", "?") if contacts else "?"
        console.print(f"  • {company} — {title} → {first_contact}")

    console.print()

    if not typer.confirm("Proceed with sending?", default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(0)

    # ── Send ──────────────────────────────────────────────────────────────
    success_count = 0
    fail_count = 0
    quota_remaining = remaining

    for t in targets:
        app = t["app"]
        job = t["job"]
        contacts = t["contacts"]
        company = job.get("company", "?")
        title = job.get("title", "?")

        for contact in contacts:
            if quota_remaining <= 0:
                console.print("[red]Daily limit reached — stopping.[/red]")
                break

            email_addr = contact.get("email", "")
            if not email_addr:
                continue

            recipient_name = contact.get("first_name")
            body = _generate_email_body(company, title, recipient_name)
            subject = f"Application for {title} position"

            ok = asyncio.run(
                sender.send_email(
                    to=email_addr,
                    subject=subject,
                    body=body,
                ),
            )

            if ok:
                success_count += 1
                quota_remaining -= 1
                # Mark application as sent in the database
                if app.get("id") is not None:
                    asyncio.run(_update_email_sent(app["id"]))
                console.print(
                    f"[green]✓[/green] Sent to {email_addr} "
                    f"({company} — {title})"
                )
            else:
                fail_count += 1
                console.print(
                    f"[red]✗[/red] Failed to send to {email_addr} "
                    f"({company} — {title})"
                )

    # ── Summary ────────────────────────────────────────────────────────────
    console.print()
    if fail_count == 0:
        console.print(
            f"[green]✓[/green] All {success_count} email(s) sent "
            f"successfully."
        )
    else:
        console.print(
            f"[yellow]⚠[/yellow] Sent {success_count}, failed {fail_count}."
        )


@email_app.command()
def draft(
    job_id: int = typer.Option(
        ...,
        "--job-id",
        "-j",
        help="Job/application ID to generate a draft for",
        prompt=True,
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save draft to a specific file path (default: data/drafts/)",
    ),
) -> None:
    """Generate and save an email draft without sending.

    Creates a plain-text draft email for the specified job using the
    application's contacts and job details.  The draft is saved locally
    for review.  Run ``internapply email send --job-id <id> --approve``
    when you are ready to send.
    """
    app = asyncio.run(_load_application(job_id))
    if app is None:
        console.print(
            f"[red]✗[/red] No application found for job ID {job_id}."
        )
        raise typer.Exit(1)

    job = asyncio.run(_load_job(app["job_id"]))
    if job is None:
        job = {}

    company = job.get("company", "?")
    title = job.get("title", "?")

    contacts = app.get("email_contacts", [])
    first_contact = contacts[0] if contacts else {}

    body = _generate_email_body(
        company,
        title,
        recipient_name=first_contact.get("first_name"),
    )

    # ── Determine save path ───────────────────────────────────────────────
    if output:
        draft_path = Path(output)
    else:
        draft_dir = Path("data/drafts")
        draft_dir.mkdir(parents=True, exist_ok=True)
        draft_path = draft_dir / f"draft_job_{job_id}.txt"

    draft_path.write_text(body, encoding="utf-8")

    console.print(f"[green]✓[/green] Draft saved to [bold]{draft_path}[/bold]")
    console.print()
    console.print(Panel(body, title=f"Draft — {company} — {title}"))
    console.print()
    console.print(
        "[dim]Review the draft above.  To send when ready:[/dim]\n"
        f"[bold]  internapply email send --job-id {job_id} --approve[/bold]"
    )


@email_app.command()
def status() -> None:
    """Show daily send count, remaining quota, and token status.

    Displays a visual progress bar of today's sends vs. the 20-email
    daily limit, plus information about the saved encrypted token.
    """
    sender = _get_sender()

    sent = sender.get_daily_send_count()
    remaining = sender.get_remaining_quota()
    total = _MAX_SENDS_PER_DAY = 20

    # ── Progress bar ──────────────────────────────────────────────────────
    bar_width = 30
    filled = int((sent / total) * bar_width) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_width - filled)

    console.print(
        Panel.fit("[bold]Email Sending Status[/bold]", border_style="blue")
    )
    console.print()

    # Determine status colour
    if remaining <= 0:
        limit_style = "red"
    elif remaining <= 5:
        limit_style = "yellow"
    else:
        limit_style = "green"

    console.print(f"  Today's sends: [bold]{sent}[/bold] / {total}")
    console.print(
        f"  Remaining:     [bold {limit_style}]{remaining}[/bold {limit_style}]"
    )
    console.print(f"  [{bar}]")

    if remaining <= 0:
        console.print()
        console.print("[red]✗[/red] Daily limit reached. Try again tomorrow.")
    elif remaining <= 5:
        console.print()
        console.print(
            "[yellow]⚠[/yellow] Warning: Approaching the daily limit "
            f"({remaining} remaining)."
        )

    # ── Token status ──────────────────────────────────────────────────────
    console.print()
    token_path = sender._get_encrypted_token_path()
    if token_path.exists():
        size = token_path.stat().st_size
        console.print(
            f"[dim]Encrypted token:[/dim] [green]✓[/green] "
            f"{token_path} ({size} bytes)"
        )
    else:
        console.print(
            "[dim]Encrypted token:[/dim] [yellow]✗ Not found[/yellow]\n"
            "  Run [bold]internapply email setup[/bold] to authenticate."
        )


@email_app.command()
def export_token(
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON for CI setup"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Save to file instead of stdout",
    ),
) -> None:
    """Export the Gmail OAuth token for CI/CD usage.

    Run this AFTER authenticating with ``internapply email setup``.
    The token JSON contains a refresh token that can be stored as a
    GitHub secret (``GMAIL_TOKEN_JSON``) for headless CI environments.

    Without ``--raw``, prints a masked preview.  With ``--raw``,
    outputs the JSON for piping into a GitHub secret::

        internapply email export-token --raw | pbcopy
        # Then paste into GitHub → Settings → Secrets → GMAIL_TOKEN_JSON
    """
    from internapply.outreach.sender import GmailSender

    sender = GmailSender()
    token_path = sender._get_encrypted_token_path()

    if not token_path.exists():
        console.print("[red]✗[/red] No token found. Run [bold]internapply email setup[/bold] first.")
        raise typer.Exit(1)

    try:
        encrypted = token_path.read_bytes()
        token_data = sender._decrypt_token(encrypted)
    except Exception as exc:
        console.print(f"[red]✗[/red] Failed to decrypt token: {exc}")
        raise typer.Exit(1)

    if raw:
        import json
        output_text = json.dumps(token_data, indent=2)
        if output:
            Path(output).write_text(output_text, encoding="utf-8")
            console.print(f"[green]✓[/green] Token saved to [bold]{output}[/bold]")
        else:
            console.print(output_text)
    else:
        console.print("[bold]Gmail Token — Preview[/bold]")
        console.print(f"  Email: {token_data.get('token', '?')[:20]}...")
        console.print(f"  Refresh token: {token_data.get('refresh_token', '?')[:20]}...")
        console.print(f"  Scopes: {token_data.get('scopes', [])}")
        console.print()
        console.print("  [dim]To export for CI:[/dim] [bold]internapply email export-token --raw[/bold]")
