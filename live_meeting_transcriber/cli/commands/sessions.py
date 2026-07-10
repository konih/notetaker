"""Session/transcript commands — list, summarize, export, speaker inspection + aliasing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

import typer

from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.cli.deps import get_container
from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.obsidian.meeting_export import ExportCancelledError, write_dual_export


def sessions(
    ctx: typer.Context,
    search: str = typer.Option(
        "",
        "--search",
        "-s",
        help="Filter by title, notes, or attendees (case-insensitive substring).",
    ),
) -> None:
    """List known meeting sessions (optionally filtered with --search)."""
    c = get_container(ctx)
    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
        session_speakers=c.session_speakers,
    )
    results = svc.search_sessions(search)
    if not results:
        typer.echo(
            f"No sessions match {search.strip()!r}." if search.strip() else "No sessions yet."
        )
        return
    for s in results:
        typer.echo(f"{s.id}  {s.started_at.isoformat()}  {s.title}")


def summarize(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    context: str | None = typer.Option(
        None,
        "--context",
        help="Optional extra guidance for the LLM (not stored in the database).",
    ),
) -> None:
    """Generate and store summary/decisions/action-items for a session."""
    c = get_container(ctx)
    sid = UUID(session_id)
    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
        session_speakers=c.session_speakers,
    )
    summary = asyncio.run(svc.summarize_session(session_id=sid, user_context=context))
    updated = c.sessions.get(sid)
    if updated is not None and summary.meeting_metadata is not None:
        title = summary.meeting_metadata.confident_str("title")
        if title and updated.title == title:
            typer.echo(f"Title: {updated.title}", err=True)
    typer.echo(summary.summary_markdown)


def export(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    format: str = typer.Option("markdown", "--format"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing export files without prompting.",
    ),
) -> None:
    """Export transcript and summary."""
    if format != "markdown":
        typer.echo("Only --format markdown is supported currently.", err=True)
        raise typer.Exit(code=2)

    c = get_container(ctx)
    sid = UUID(session_id)
    session = c.sessions.get(sid)
    if session is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)

    segments = c.transcripts.list_by_session(sid)
    summary = c.summaries.get_by_session(sid)
    spk = c.session_speakers.get_map(sid)

    def confirm_overwrite(path: Path) -> bool:
        if force:
            return True
        if not sys.stdin.isatty():
            typer.echo(
                f"Export skipped (file exists with different content): {path}. Use --force.",
                err=True,
            )
            return False
        return typer.confirm(
            f"Export file exists with different content:\n{path}\nOverwrite?",
            default=False,
        )

    try:
        result = write_dual_export(
            app_base_dir=c.settings.ensure_data_dir(),
            session=session,
            segments=segments,
            summary=summary,
            speaker_display=spk if spk else None,
            obsidian_meetings_dir=c.settings.obsidian_meetings_dir,
            obsidian_meeting_template=c.settings.obsidian_meeting_template,
            screenshots_source_dir=c.settings.effective_screenshots_source_dir(),
            obsidian_screenshots_dir=c.settings.obsidian_screenshots_dir,
            confirm_overwrite=confirm_overwrite,
        )
    except ExportCancelledError as e:
        typer.echo(f"Export cancelled: {e.path}", err=True)
        raise typer.Exit(code=1) from e

    typer.echo(result.app_path.read_text(encoding="utf-8"))
    typer.echo("", err=False)
    if result.app_written:
        typer.echo(f"Wrote: {result.app_path}", err=False)
    elif result.app_path.is_file():
        typer.echo(f"Unchanged: {result.app_path}", err=False)
    if result.obs_path is not None:
        if result.obs_written:
            typer.echo(f"Obsidian meeting: {result.obs_path}", err=False)
        else:
            typer.echo(f"Obsidian unchanged: {result.obs_path}", err=False)


def list_speakers(ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")) -> None:
    """List speakers from transcript, stored diarization intervals, and aliases."""
    c = get_container(ctx)
    sid = UUID(session_id)
    if c.sessions.get(sid) is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)
    segs = c.transcripts.list_by_session(sid)
    t_keys = sorted({s.speaker for s in segs})
    diar = c.diarization_segments.list_by_session(sid)
    d_keys = sorted({d.speaker_key for d in diar})
    typer.echo("Transcript speaker keys: " + (", ".join(t_keys) if t_keys else "—"))
    typer.echo("Diarization speaker keys: " + (", ".join(d_keys) if d_keys else "—"))
    for a in c.session_speakers.list_aliases(sid):
        typer.echo(f"  alias: {a.speaker_key} -> {a.display_name}")


def speaker_alias(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    speaker: str = typer.Option(..., "--speaker", help="e.g. speaker_1 or SPEAKER_00"),
    name: str = typer.Option(..., "--name", help="Display name"),
) -> None:
    """Map a diarization speaker key to a display name for exports and summaries."""
    c = get_container(ctx)
    sid = UUID(session_id)
    if c.sessions.get(sid) is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)
    raw = speaker.strip()
    key = normalize_pyannote_speaker_label(raw) if raw.upper().startswith("SPEAKER_") else raw
    c.session_speakers.set_alias(sid, key, name.strip())
    typer.echo(f"Saved alias {key!r} -> {name.strip()!r} for session {sid}")
