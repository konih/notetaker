"""Offline finalize / diarization commands: ``finalize``, ``finalize-pending``, ``doctor``."""

from __future__ import annotations

from uuid import UUID

import typer
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from live_meeting_transcriber.application.finalize_service import (
    finalize_session_sync,
    find_unfinalized_sessions,
    session_speakers_are_all_unknown,
)
from live_meeting_transcriber.cli.deps import get_container
from live_meeting_transcriber.config.settings import load_settings

_SPEAKERS_UNLABELLED_HINT = (
    "Speakers were NOT labelled — WhisperX ran but diarization produced no speakers. "
    "Set HF_TOKEN (pyannote) and install the whisperx extra (uv sync --extra whisperx)."
)


def finalize_session(
    ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")
) -> None:
    """Run offline WhisperX + diarization on ``full_session.wav`` and replace the transcript."""
    c = get_container(ctx)
    sid = UUID(session_id)
    if c.sessions.get(sid) is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)
    try:
        n = finalize_session_sync(container=c, settings=c.settings, session_id=sid)
    except ImportError as e:
        typer.echo(f"Install WhisperX: uv sync --extra whisperx ({e})", err=True)
        raise typer.Exit(code=2) from e
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e
    typer.echo(f"Replaced transcript with {n} segment(s).")
    if session_speakers_are_all_unknown(container=c, session_id=sid):
        typer.echo(_SPEAKERS_UNLABELLED_HINT, err=True)


def finalize_pending(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="List sessions that would be finalized without running WhisperX."
    ),
) -> None:
    """Backfill speaker ID for sessions that never got diarized.

    Auto-finalize-on-stop schedules a background task when a recording stops;
    if the app is closed shortly after, that task is killed before WhisperX
    finishes and the session is left with every transcript segment stuck on
    "unknown" forever. A recording that was *interrupted* (app crash / force-quit)
    additionally never got its ``ended_at`` set, so it looks like it is still
    recording — but its ``full_session.wav`` survives on disk and is recoverable.
    This finds both (non-empty transcript, every segment still "unknown"; ended,
    or interrupted-with-a-surviving-recording) and re-runs finalize for each.
    """
    c = get_container(ctx)
    pending = find_unfinalized_sessions(
        container=c, include_interrupted=True, data_dir=c.settings.ensure_data_dir()
    )
    if not pending:
        typer.echo("No pending sessions found (nothing to finalize).")
        return

    typer.echo(f"Found {len(pending)} session(s) never diarized:")
    for session in pending:
        typer.echo(f"  {session.id}  {session.started_at.isoformat()}  {session.title}")
    if dry_run:
        typer.echo("Dry run: not running WhisperX.")
        return

    ok = 0
    failed = 0
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    ) as progress:
        task_id = progress.add_task("Finalizing", total=len(pending))
        for session in pending:
            progress.update(task_id, description=f"Finalizing {session.title[:40]}")
            try:
                n = finalize_session_sync(container=c, settings=c.settings, session_id=session.id)
                if session_speakers_are_all_unknown(container=c, session_id=session.id):
                    typer.echo(
                        f"  ok (speakers NOT labelled): {session.id} -> {n} segment(s). "
                        f"{_SPEAKERS_UNLABELLED_HINT}"
                    )
                else:
                    typer.echo(f"  ok: {session.id} -> {n} segment(s)")
                ok += 1
            except Exception as e:
                typer.echo(f"  failed: {session.id}: {e}", err=True)
                failed += 1
            progress.advance(task_id)
    typer.echo(f"Done: {ok} succeeded, {failed} failed.")
    if failed:
        raise typer.Exit(code=1)


def doctor() -> None:
    """Check offline-diarization prerequisites (extras, ffmpeg, HF token, gated model, device).

    Runs each check and prints a pass/fail line with a copy-pasteable fix. Exits 0 when every
    prerequisite is satisfied, otherwise exits 1 and names the first thing to fix.
    """
    from live_meeting_transcriber.diagnostics.diarization_doctor import (
        all_ok,
        run_diarization_checks,
    )

    settings = load_settings()
    results = run_diarization_checks(settings)
    for r in results:
        typer.echo(f"[{'OK  ' if r.ok else 'FAIL'}] {r.name}: {r.detail}")
        if not r.ok and r.remediation:
            typer.echo(f"       -> {r.remediation}")
    if all_ok(results):
        typer.echo("\nAll diarization prerequisites satisfied.")
        return
    first_fail = next(r for r in results if not r.ok)
    typer.echo(f"\nFix first: {first_fail.name}", err=True)
    raise typer.Exit(code=1)
