"""Main CLI entrypoint for InternApply.

Usage::

    internapply --help
    internapply resume init
    internapply resume show
"""

from __future__ import annotations

import typer

from internapply.cli.resume import resume_app

app = typer.Typer(
    name="internapply",
    help="Automated internship application system",
    no_args_is_help=True,
)

app.add_typer(resume_app, name="resume", help="Manage resume data")

if __name__ == "__main__":
    app()
