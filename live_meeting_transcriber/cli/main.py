from __future__ import annotations

import asyncio
import atexit
from uuid import UUID

import typer

from live_meeting_transcriber.application.container import Container, build_container
from live_meeting_transcriber.obsidian.meeting_export import write_dual_export
from live_meeting_transcriber.application.diarization_batch import reprocess_session_diarization
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.audio.sources import resolve_microphone_source
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
    default_mic = c.devices.get_default_microphone_source()

    for s in sources:
        if default_monitor and s.name == default_monitor:
            prefix = "* "
        elif default_mic and s.name == default_mic:
            prefix = "^ "
        else:
            prefix = "  "
        typer.echo(f"{prefix}{s.name}")
    typer.echo("", err=False)
    typer.echo("* = default monitor (playback)   ^ = default microphone (capture)", err=False)


@app.command()
def sessions(ctx: typer.Context) -> None:
    """List known meeting sessions."""
    c = _get_container(ctx)
    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
        session_speakers=c.session_speakers,
    )
    for s in svc.list_sessions():
        typer.echo(f"{s.id}  {s.started_at.isoformat()}  {s.title}")


@app.command()
def record(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Meeting title"),
    source: str | None = typer.Option(None, "--source", help="PulseAudio source name (e.g. <sink>.monitor)"),
    microphone_source: str | None = typer.Option(
        None,
        "--microphone-source",
        help="PulseAudio mic source; default: default capture device",
    ),
    no_microphone: bool = typer.Option(
        False,
        "--no-microphone",
        help="Monitor/system audio only (disable microphone mix for this run)",
    ),
    chunk_seconds: int | None = typer.Option(None, "--chunk-seconds", help="Chunk duration in seconds"),
) -> None:
    """Capture system audio in chunks and print transcript segments to stdout."""
    c = _get_container(ctx)
    log = get_logger(component="cli")

    monitor = source or c.devices.get_default_monitor_source()
    if not monitor:
        typer.echo("Could not auto-detect default monitor source. Use `live-transcriber devices`.", err=True)
        raise typer.Exit(code=2)

    mic = resolve_microphone_source(
        c.settings,
        c.devices,
        cli_explicit=microphone_source,
        cli_no_microphone=no_microphone,
    )
    if c.settings.audio_include_microphone and not no_microphone and mic is None:
        log.warning(
            "microphone_unavailable",
            message="Recording monitor only; set AUDIO_MICROPHONE_SOURCE or check Default Source.",
        )

    svc = SessionService(
        sessions=c.sessions,
        transcripts=c.transcripts,
        summaries=c.summaries,
        summarizer=c.summarizer,
        session_speakers=c.session_speakers,
    )
    session = svc.create_session(title=title)
    log.info("session_started", session_id=str(session.id), title=title)

    chunk_dir = (c.settings.ensure_data_dir() / "chunks" / str(session.id)).resolve()
    recorder = Recorder(
        audio=c.audio,
        transcriber=c.transcriber,
        diarizer=c.diarizer,
        transcripts=c.transcripts,
        diarization_segments=c.diarization_segments,
        keep_audio_chunks=c.settings.keep_audio_chunks,
        chunk_output_dir=chunk_dir,
        diarization_enabled=c.settings.diarization_enabled,
    )

    async def _run() -> None:
        await recorder.record_forever(
            session_id=session.id,
            source=monitor,
            microphone_source=mic,
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
        session_speakers=c.session_speakers,
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
    spk = c.session_speakers.get_map(sid)
    app_path, obs_path = write_dual_export(
        app_base_dir=c.settings.ensure_data_dir(),
        session=session,
        segments=segments,
        summary=summary,
        speaker_display=spk if spk else None,
        obsidian_meetings_dir=c.settings.obsidian_meetings_dir,
        obsidian_meeting_template=c.settings.obsidian_meeting_template,
        screenshots_source_dir=c.settings.effective_screenshots_source_dir(),
        obsidian_screenshots_dir=c.settings.obsidian_screenshots_dir,
    )
    typer.echo(app_path.read_text(encoding="utf-8"))
    typer.echo("", err=False)
    typer.echo(f"Wrote: {app_path}", err=False)
    if obs_path is not None:
        typer.echo(f"Obsidian meeting: {obs_path}", err=False)


@app.command()
def diarize(ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")) -> None:
    """Re-run speaker diarization on stored chunk WAVs and update transcript speakers."""
    c = _get_container(ctx)
    if not c.settings.diarization_enabled:
        typer.echo("Enable DIARIZATION_ENABLED and set DIARIZATION_PROVIDER (e.g. pyannote).", err=True)
        raise typer.Exit(code=2)
    sid = UUID(session_id)
    if c.sessions.get(sid) is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)
    chunk_dir = (c.settings.ensure_data_dir() / "chunks" / str(sid)).resolve()

    async def _run() -> tuple[int, int]:
        return await reprocess_session_diarization(
            transcripts=c.transcripts,
            diarizer=c.diarizer,
            diarization_repo=c.diarization_segments,
            chunk_dir=chunk_dir,
            session_id=sid,
            sample_rate_hz=c.settings.audio_sample_rate,
            channels=c.settings.audio_channels,
        )

    chunks, updated = asyncio.run(_run())
    typer.echo(f"Diarized {chunks} chunk WAV file(s); updated {updated} transcript line(s).")


@app.command("speakers")
def list_speakers(ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")) -> None:
    """List speakers from transcript, stored diarization intervals, and aliases."""
    c = _get_container(ctx)
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


@app.command("speaker-alias")
def speaker_alias(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    speaker: str = typer.Option(..., "--speaker", help="e.g. speaker_1 or SPEAKER_00"),
    name: str = typer.Option(..., "--name", help="Display name"),
) -> None:
    """Map a diarization speaker key to a display name for exports and summaries."""
    c = _get_container(ctx)
    sid = UUID(session_id)
    if c.sessions.get(sid) is None:
        typer.echo("Unknown session id.", err=True)
        raise typer.Exit(code=2)
    raw = speaker.strip()
    key = normalize_pyannote_speaker_label(raw) if raw.upper().startswith("SPEAKER_") else raw
    c.session_speakers.set_alias(sid, key, name.strip())
    typer.echo(f"Saved alias {key!r} -> {name.strip()!r} for session {sid}")

