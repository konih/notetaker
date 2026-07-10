"""``cleanup`` command — purge session artifacts, orphans, caches (dry-run by default)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer

from live_meeting_transcriber.application.cleanup_service import run_cleanup
from live_meeting_transcriber.cli.deps import get_container


def cleanup(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="List artifacts without deleting (default).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm destructive deletion (equivalent to --no-dry-run).",
    ),
    session_id: Annotated[
        list[str] | None,
        typer.Option(
            "--session-id",
            help="Purge artifacts for one or more session UUIDs (repeatable)",
        ),
    ] = None,
    all_sessions: bool = typer.Option(
        False,
        "--all-sessions",
        help="Purge artifacts for every session in the database",
    ),
    orphans: bool = typer.Option(
        False,
        "--orphans",
        help="Remove chunk/session/preview dirs with no matching DB row",
    ),
    imports_cache: bool = typer.Option(
        False,
        "--imports-cache",
        help="Clear downloaded video cache under imports/downloads",
    ),
    logs: bool = typer.Option(
        False,
        "--logs",
        help="Remove rotated application log files",
    ),
    exports: bool = typer.Option(
        False,
        "--exports",
        help="Remove all markdown/screenshot exports",
    ),
) -> None:
    """Remove session artifacts, orphans, or cached imports (dry-run by default)."""
    c = get_container(ctx)
    if yes:
        dry_run = False

    if not any((session_id, all_sessions, orphans, imports_cache, logs, exports)):
        typer.echo(
            "Specify at least one target: --session-id, --all-sessions, --orphans, "
            "--imports-cache, --logs, or --exports.",
            err=True,
        )
        raise typer.Exit(code=2)

    known = {s.id for s in c.sessions.list()}
    session_uuids: list[UUID] = []
    for sid in session_id or []:
        try:
            session_uuids.append(UUID(sid))
        except ValueError:
            typer.echo(f"Invalid session id: {sid}", err=True)
            raise typer.Exit(code=2) from None

    report = run_cleanup(
        c.settings.ensure_data_dir(),
        known_session_ids=known,
        session_ids=session_uuids or None,
        all_sessions=all_sessions,
        orphans=orphans,
        imports_cache=imports_cache,
        logs=logs,
        exports=exports,
        dry_run=dry_run,
    )

    mode = "Would remove" if dry_run else "Removed"
    for purge in report.session_purges:
        for path in purge.paths:
            typer.echo(f"{mode}: {path}")
    for label, purge in (
        ("orphan", report.orphan_purges),
        ("imports-cache", report.imports_cache_purge),
        ("logs", report.logs_purge),
        ("exports", report.exports_purge),
    ):
        for path in purge.paths:
            typer.echo(f"{mode} ({label}): {path}")

    typer.echo(f"{mode} {report.total_paths} path(s) total.", err=False)
    if dry_run:
        typer.echo("Re-run with --yes to delete.", err=False)
