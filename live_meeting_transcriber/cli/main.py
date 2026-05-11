from __future__ import annotations

import asyncio
import atexit
from uuid import UUID

import typer

from live_meeting_transcriber.application.container import Container, build_container
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.config.settings import load_settings
from live_meeting_transcriber.observability.logging import configure_logging, get_logger


app = typer.Typer(add_completion=False, help="Live background meeting transcription (Ubuntu/Linux).")


def _get_container(ctx: typer.Context) -> Container:
    c = ctx.obj
    if not isinstance(c, Container):
        raise typer.Exit(code=2)
    return c


@app.callback()
def _main_callback(ctx: typer.Context) -> None:
    settings = load_settings()
    log_path = settings.resolved_log_file() if settings.log_enable_file else None
    configure_logging(
        settings.log_level,
        log_file=log_path,
        log_file_max_bytes=settings.log_file_max_bytes,
        log_file_backup_count=settings.log_file_backup_count,
    )
    container = build_container(settings)
    atexit.register(container.close)
    ctx.obj = container


@app.command()
def tui(ctx: typer.Context) -> None:
    """Interactive terminal UI (live status, transcript, settings)."""
    from live_meeting_transcriber.ui.tui.app import run_tui_attached

    run_tui_attached(
        container=_get_container(ctx),
        settings=load_settings(),
        configure_log=False,
    )


@app.command()
def devices(ctx: typer.Context) -> None:
    """List available PulseAudio/PipeWire sources (including monitor sources)."""
    c = _get_container(ctx)
    sources = c.devices.list_sources()
    default_monitor = c.devices.get_default_monitor_source()

    for s in sources:
        prefix = "* " if default_monitor and s.name == default_monitor else "  "
        typer.echo(f"{prefix}{s.name}")


@app.command()
def sessions(ctx: typer.Context) -> None:
    """List known meeting sessions."""
    c = _get_container(ctx)
    svc = SessionService(
        sessions=c.sessions, transcripts=c.transcripts, summaries=c.summaries, summarizer=c.summarizer
    )
    for s in svc.list_sessions():
        typer.echo(f"{s.id}  {s.started_at.isoformat()}  {s.title}")


@app.command()
def record(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Meeting title"),
    source: str | None = typer.Option(None, "--source", help="PulseAudio source name (e.g. <sink>.monitor)"),
    chunk_seconds: int | None = typer.Option(None, "--chunk-seconds", help="Chunk duration in seconds"),
) -> None:
    """Capture system audio in chunks and print transcript segments to stdout."""
    c = _get_container(ctx)
    log = get_logger(component="cli")

    monitor = source or c.devices.get_default_monitor_source()
    if not monitor:
        typer.echo("Could not auto-detect default monitor source. Use `live-transcriber devices`.", err=True)
        raise typer.Exit(code=2)

    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
    )
    session = svc.create_session(title=title)
    log.info("session_started", session_id=str(session.id), title=title)

    chunk_dir = (c.settings.ensure_data_dir() / "chunks" / str(session.id)).resolve()
    recorder = Recorder(
        audio=c.audio,
        transcriber=c.transcriber,
        diarizer=c.diarizer,
        transcripts=c.transcripts,
        keep_audio_chunks=c.settings.keep_audio_chunks,
        chunk_output_dir=chunk_dir,
    )

    async def _run() -> None:
        await recorder.record_forever(
            session_id=session.id,
            source=monitor,
            chunk_seconds=chunk_seconds or c.settings.audio_chunk_seconds,
            sample_rate_hz=c.settings.audio_sample_rate,
            channels=c.settings.audio_channels,
            on_segment=lambda seg: typer.echo(f"[{seg.started_at.isoformat()}] {seg.text}"),
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        # Treat Ctrl-C as a normal shutdown: keep whatever was already captured.
        log.info("recording_stopped_by_user", session_id=str(session.id))
    finally:
        try:
            c.sessions.end(session.id)
        except Exception:
            pass
        log.info("session_ended", session_id=str(session.id))


@app.command()
def summarize(ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")) -> None:
    """Generate and store summary/decisions/action-items for a session."""
    c = _get_container(ctx)
    sid = UUID(session_id)
    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
    )
    summary = asyncio.run(svc.summarize_session(session_id=sid))
    typer.echo(summary.summary_markdown)


@app.command()
def export(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    format: str = typer.Option("markdown", "--format"),
) -> None:
    """Export transcript and summary."""
    if format != "markdown":
        typer.echo("Only --format markdown is supported currently.", err=True)
        raise typer.Exit(code=2)

    c = _get_container(ctx)
    sid = UUID(session_id)
    session = c.sessions.get(sid)
    if session is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)

    segments = c.transcripts.list_by_session(sid)
    summary = c.summaries.get_by_session(sid)

    lines: list[str] = []
    lines.append(f"## {session.title}")
    lines.append("")
    lines.append(f"- **Session ID**: `{session.id}`")
    lines.append(f"- **Started**: {session.started_at.isoformat()}")
    lines.append(f"- **Ended**: {session.ended_at.isoformat() if session.ended_at else ''}")
    lines.append("")

    if summary:
        lines.append("### Summary")
        lines.append("")
        lines.append(summary.summary_markdown)
        lines.append("")
        if summary.decisions:
            lines.append("### Decisions")
            lines.append("")
            for d in summary.decisions:
                lines.append(f"- {d.text}")
            lines.append("")
        if summary.action_items:
            lines.append("### Action items")
            lines.append("")
            for ai in summary.action_items:
                lines.append(f"- {ai.text}")
            lines.append("")

    lines.append("### Transcript")
    lines.append("")
    for s in segments:
        lines.append(f"- [{s.started_at.isoformat()}] {s.text}")

    typer.echo("\n".join(lines))

