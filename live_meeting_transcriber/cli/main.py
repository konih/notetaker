from __future__ import annotations

import asyncio
import atexit
import sys
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from live_meeting_transcriber.application.cleanup_service import run_cleanup
from live_meeting_transcriber.application.container import (
    Container,
    ProviderSelectionError,
    build_container,
)
from live_meeting_transcriber.application.finalize_service import (
    finalize_session_sync,
    find_unfinalized_sessions,
    session_speakers_are_all_unknown,
)
from live_meeting_transcriber.application.path_sanitize import normalize_import_path
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.application.slide_preview_service import (
    SlidePreviewError,
    SlidePreviewService,
)
from live_meeting_transcriber.application.video_import_service import (
    VideoImportError,
    VideoImportProgress,
    VideoImportService,
)
from live_meeting_transcriber.audio.platform import audio_backend
from live_meeting_transcriber.audio.sources import resolve_microphone_source
from live_meeting_transcriber.config.settings import Settings, load_settings
from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.domain.models import SlideDetectionParams
from live_meeting_transcriber.domain.ports import MeetingSessionRepository
from live_meeting_transcriber.observability.logging import configure_logging, get_logger
from live_meeting_transcriber.obsidian.meeting_export import ExportCancelledError, write_dual_export

app = typer.Typer(
    add_completion=False,
    help="Live background meeting transcription (Linux and macOS).",
)
slides_app = typer.Typer(help="Preview and apply slide detection on imported video sessions.")
app.add_typer(slides_app, name="slides")


def _get_container(ctx: typer.Context) -> Container:
    c = ctx.obj
    if not isinstance(c, Container):
        raise typer.Exit(code=2)
    return c


def _end_session_safely(sessions: MeetingSessionRepository, session_id: UUID, *, log: Any) -> None:
    """End a session, surfacing a failed end instead of silently swallowing it (ARCH-07).

    A failed ``sessions.end`` is logged and reported to stderr; the clean
    ``session_ended`` event is only emitted when the end actually succeeded.
    """
    try:
        sessions.end(session_id)
    except Exception:
        log.warning("session_end_failed", session_id=str(session_id), exc_info=True)
        typer.echo(
            "warning: failed to finalize the session cleanly; see logs for details",
            err=True,
        )
    else:
        log.info("session_ended", session_id=str(session_id))


@app.callback(invoke_without_command=True)
def _main_callback(ctx: typer.Context) -> None:
    settings = load_settings()
    log_path = settings.resolved_log_file() if settings.log_enable_file else None
    configure_logging(
        settings.log_level,
        log_file=log_path,
        log_file_max_bytes=settings.log_file_max_bytes,
        log_file_backup_count=settings.log_file_backup_count,
    )
    try:
        container = build_container(settings)
    except ProviderSelectionError as e:
        # Provider misconfiguration (e.g. missing OPENAI_API_KEY) is a user error,
        # not a bug: show the actionable message instead of a Python traceback.
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2) from e
    atexit.register(container.close)
    ctx.obj = container

    if ctx.invoked_subcommand is None:
        from live_meeting_transcriber.ui.tui.app import run_tui_attached

        run_tui_attached(
            container=container,
            settings=settings,
            configure_log=False,
        )
        raise typer.Exit()


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
    """List available audio capture devices (PulseAudio/PipeWire on Linux, AVFoundation on macOS)."""
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
        if audio_backend() == "avfoundation":
            typer.echo(f"{prefix}{s.name}  {s.description}")
        else:
            typer.echo(f"{prefix}{s.name}")
    typer.echo("", err=False)
    typer.echo("* = default monitor (playback)   ^ = default microphone (capture)", err=False)
    if audio_backend() == "avfoundation" and default_monitor is None:
        typer.echo(
            "macOS: no virtual loopback detected — install BlackHole or route meeting audio "
            "through a virtual device, then set --source or AUDIO_MICROPHONE_SOURCE.",
            err=False,
        )


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
    source: str | None = typer.Option(
        None,
        "--source",
        help="PulseAudio/PipeWire or AVFoundation source (e.g. <sink>.monitor or :3)",
    ),
    microphone_source: str | None = typer.Option(
        None,
        "--microphone-source",
        help="Microphone source; default: default capture device",
    ),
    no_microphone: bool = typer.Option(
        False,
        "--no-microphone",
        help="Monitor/system audio only (disable microphone mix for this run)",
    ),
    chunk_seconds: int | None = typer.Option(
        None, "--chunk-seconds", help="Chunk duration in seconds"
    ),
) -> None:
    """Capture system audio in chunks and print transcript segments to stdout."""
    c = _get_container(ctx)
    log = get_logger(component="cli")

    monitor = source or c.devices.get_default_monitor_source()
    if not monitor:
        typer.echo(
            "Could not auto-detect default monitor source. Use `live-transcriber devices`.",
            err=True,
        )
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
        transcripts=c.transcripts,
        keep_audio_chunks=c.settings.keep_audio_chunks,
        chunk_output_dir=chunk_dir,
        data_dir=c.settings.ensure_data_dir(),
        audio_stereo_mode=c.settings.audio_stereo_mode,
        transcription_provider=c.settings.transcription_provider,
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
        _end_session_safely(c.sessions, session.id, log=log)


@app.command()
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
    c = _get_container(ctx)
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


@app.command()
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

    c = _get_container(ctx)
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


_SPEAKERS_UNLABELLED_HINT = (
    "Speakers were NOT labelled — WhisperX ran but diarization produced no speakers. "
    "Set HF_TOKEN (pyannote) and install the whisperx extra (uv sync --extra whisperx)."
)


@app.command("finalize")
def finalize_session(
    ctx: typer.Context, session_id: str = typer.Option(..., "--session-id")
) -> None:
    """Run offline WhisperX + diarization on ``full_session.wav`` and replace the transcript."""
    c = _get_container(ctx)
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


@app.command("finalize-pending")
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
    c = _get_container(ctx)
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


def _slide_params_from_cli(
    *,
    sample_interval: float | None,
    threshold: float | None,
    min_interval: float | None,
    max_candidates: int | None,
    settings: Settings,
) -> SlideDetectionParams | None:
    if all(v is None for v in (sample_interval, threshold, min_interval, max_candidates)):
        return None
    base = settings.slide_detection_params()
    return SlideDetectionParams(
        sample_interval_seconds=sample_interval
        if sample_interval is not None
        else base.sample_interval_seconds,
        change_threshold=threshold if threshold is not None else base.change_threshold,
        min_slide_interval_seconds=min_interval
        if min_interval is not None
        else base.min_slide_interval_seconds,
        max_candidates=max_candidates if max_candidates is not None else base.max_candidates,
    )


@app.command("transcribe-video")
def transcribe_video(
    ctx: typer.Context,
    source: str = typer.Option(
        ...,
        "--source",
        help="Local video path or http(s) URL (YouTube etc.; requires yt-dlp for URLs)",
    ),
    title: str | None = typer.Option(
        None, "--title", help="Session title (default: from filename)"
    ),
    chunk_seconds: int | None = typer.Option(
        None, "--chunk-seconds", help="Transcription chunk size in seconds"
    ),
    no_slides: bool = typer.Option(
        False, "--no-slides", help="Skip slide detection and screenshot extraction"
    ),
    yes_slides: bool = typer.Option(
        False,
        "--yes-slides",
        help="Accept all detected slide candidates without interactive review",
    ),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Slide detection strategy: frame_diff or ffmpeg_scene",
    ),
    sample_interval: float | None = typer.Option(
        None, "--sample-interval", help="Seconds between frame samples"
    ),
    threshold: float | None = typer.Option(
        None, "--threshold", help="Change threshold (strategy-specific)"
    ),
    min_interval: float | None = typer.Option(
        None, "--min-interval", help="Minimum seconds between saved slides"
    ),
    max_candidates: int | None = typer.Option(
        None, "--max-candidates", help="Maximum slide candidates to detect"
    ),
    preview_only: bool = typer.Option(
        False,
        "--preview-only",
        help="Detect slides only; do not save (shows candidate summary)",
    ),
) -> None:
    """Transcribe a video file or URL and optionally extract presentation slide screenshots."""
    source = normalize_import_path(source)
    c = _get_container(ctx)
    log = get_logger(component="cli")

    svc = VideoImportService(
        settings=c.settings,
        sessions=c.sessions,
        transcripts=c.transcripts,
        transcriber=c.transcriber,
    )
    slide_params = _slide_params_from_cli(
        sample_interval=sample_interval,
        threshold=threshold,
        min_interval=min_interval,
        max_candidates=max_candidates,
        settings=c.settings,
    )

    async def _run() -> None:
        if preview_only:
            result = await svc.import_video(
                source=source,
                title=title,
                extract_slides=False,
                skip_transcription=True,
            )
            preview_svc = SlidePreviewService(settings=c.settings, sessions=c.sessions)
            preview = await preview_svc.preview(
                session_id=result.session_id,
                strategy=strategy,
                params=slide_params,
            )
            typer.echo("", err=False)
            typer.echo(f"Session: {result.session_id}", err=False)
            typer.echo(
                f"Preview ({preview.strategy}): {len(preview.candidates)} candidate(s)",
                err=False,
            )
            for i, cand in enumerate(preview.candidates, start=1):
                typer.echo(
                    f"  [{i}] t={cand.timestamp_seconds:.1f}s score={cand.change_score:.2f}",
                    err=False,
                )
            return

        progress_task: TaskID | None = None
        progress: Progress | None = None

        def _on_progress(p: VideoImportProgress) -> None:
            nonlocal progress, progress_task
            if p.phase == "slides":
                if progress is not None and progress_task is not None:
                    progress.update(progress_task, description="Detecting slides")
                return
            if progress is None:
                progress = Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    TimeElapsedColumn(),
                    transient=False,
                )
                progress.start()
                progress_task = progress.add_task("Transcribing", total=max(p.chunk_total, 1))
            assert progress_task is not None
            progress.update(
                progress_task,
                completed=p.chunk_index,
                description=(
                    f"Chunk {p.chunk_index}/{p.chunk_total} @ {p.offset_seconds:.0f}s "
                    f"({p.segments_so_far} segment(s))"
                ),
            )

        try:
            result = await svc.import_video(
                source=source,
                title=title,
                chunk_seconds=chunk_seconds,
                extract_slides=not no_slides,
                accept_all_slides=yes_slides,
                reject_all_slides=no_slides,
                slide_strategy=strategy,
                slide_params=slide_params,
                on_segment=lambda seg: typer.echo(f"[{seg.started_at.isoformat()}] {seg.text}"),
                on_progress=_on_progress,
            )
        finally:
            if progress is not None:
                progress.stop()

        typer.echo("", err=False)
        typer.echo(f"Session: {result.session_id}", err=False)
        summary_line = (
            f"Transcript segments: {result.segment_count}; slides saved: {result.slide_count}"
        )
        if result.transcription is not None:
            tx = result.transcription
            summary_line += (
                f" ({tx.segments} from {tx.chunks} chunk(s)"
                f"; skipped {tx.skipped_empty} empty, {tx.skipped_silent} silent"
                f"; failed {tx.failed})"
            )
        typer.echo(summary_line, err=False)
        if result.transcription is not None:
            warning = result.transcription.status_message()
            if warning is not None and result.transcription.segments > 0:
                typer.echo(f"Warning: {warning}", err=True)
        log.info(
            "transcribe_video_done",
            session_id=str(result.session_id),
            segments=result.segment_count,
            slides=result.slide_count,
        )

    try:
        asyncio.run(_run())
    except VideoImportError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e


@slides_app.command("preview")
def slides_preview(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    strategy: str | None = typer.Option(
        None,
        "--strategy",
        help="Slide detection strategy: frame_diff or ffmpeg_scene",
    ),
    sample_interval: float | None = typer.Option(
        None, "--sample-interval", help="Seconds between frame samples"
    ),
    threshold: float | None = typer.Option(
        None, "--threshold", help="Change threshold (strategy-specific)"
    ),
    min_interval: float | None = typer.Option(
        None, "--min-interval", help="Minimum seconds between saved slides"
    ),
    max_candidates: int | None = typer.Option(
        None, "--max-candidates", help="Maximum slide candidates to detect"
    ),
) -> None:
    """Re-run slide detection on an imported video session (no re-transcribe)."""
    c = _get_container(ctx)
    sid = UUID(session_id)
    params = _slide_params_from_cli(
        sample_interval=sample_interval,
        threshold=threshold,
        min_interval=min_interval,
        max_candidates=max_candidates,
        settings=c.settings,
    )
    svc = SlidePreviewService(settings=c.settings, sessions=c.sessions)

    async def _run() -> None:
        preview = await svc.preview(session_id=sid, strategy=strategy, params=params)
        typer.echo(f"Strategy: {preview.strategy}")
        typer.echo(f"Video: {preview.video_path}")
        typer.echo(f"Candidates: {len(preview.candidates)}")
        for i, cand in enumerate(preview.candidates, start=1):
            preview_note = f"  preview={cand.preview_path}" if cand.preview_path else ""
            typer.echo(
                f"  [{i}] t={cand.timestamp_seconds:.1f}s score={cand.change_score:.2f}{preview_note}"
            )

    try:
        asyncio.run(_run())
    except SlidePreviewError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e


@slides_app.command("apply")
def slides_apply(
    ctx: typer.Context,
    session_id: str = typer.Option(..., "--session-id"),
    strategy: str | None = typer.Option(None, "--strategy"),
    sample_interval: float | None = typer.Option(None, "--sample-interval"),
    threshold: float | None = typer.Option(None, "--threshold"),
    min_interval: float | None = typer.Option(None, "--min-interval"),
    max_candidates: int | None = typer.Option(None, "--max-candidates"),
    yes_slides: bool = typer.Option(
        False, "--yes-slides", help="Accept all detected candidates without prompts"
    ),
) -> None:
    """Detect slides, optionally review, and save PNGs + slides.json for a session."""
    c = _get_container(ctx)
    sid = UUID(session_id)
    params = _slide_params_from_cli(
        sample_interval=sample_interval,
        threshold=threshold,
        min_interval=min_interval,
        max_candidates=max_candidates,
        settings=c.settings,
    )
    svc = SlidePreviewService(settings=c.settings, sessions=c.sessions)

    async def _run() -> None:
        preview = await svc.preview(session_id=sid, strategy=strategy, params=params)
        saved = await svc.apply(
            session_id=sid,
            candidates=preview.candidates,
            accept_all=yes_slides,
        )
        typer.echo(f"Saved {saved} slide(s) for session {sid}")

    try:
        asyncio.run(_run())
    except SlidePreviewError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e


@app.command()
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
    c = _get_container(ctx)
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
