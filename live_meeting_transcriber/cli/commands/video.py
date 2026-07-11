"""Video import + slide detection commands: ``transcribe-video`` and ``slides preview/apply``."""

from __future__ import annotations

import asyncio
from uuid import UUID

import typer
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from live_meeting_transcriber.application.path_sanitize import normalize_import_path
from live_meeting_transcriber.application.slide_preview_service import (
    SlidePreviewError,
    SlidePreviewService,
)
from live_meeting_transcriber.application.video_import_service import (
    VideoImportError,
    VideoImportProgress,
    VideoImportService,
)
from live_meeting_transcriber.cli.deps import get_container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import SlideDetectionParams
from live_meeting_transcriber.observability.logging import get_logger


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
    c = get_container(ctx)
    log = get_logger(component="cli")

    svc = VideoImportService(
        settings=c.settings,
        sessions=c.sessions,
        transcripts=c.transcripts,
        transcriber=c.transcriber,
        media=c.media_importer,
        wav_ops=c.wav_ops,
        session_audio=c.session_audio,
        slide_tools=c.slide_tools,
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
            preview_svc = SlidePreviewService(
                settings=c.settings,
                sessions=c.sessions,
                media=c.media_importer,
                slide_tools=c.slide_tools,
            )
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
    c = get_container(ctx)
    sid = UUID(session_id)
    params = _slide_params_from_cli(
        sample_interval=sample_interval,
        threshold=threshold,
        min_interval=min_interval,
        max_candidates=max_candidates,
        settings=c.settings,
    )
    svc = SlidePreviewService(
        settings=c.settings,
        sessions=c.sessions,
        media=c.media_importer,
        slide_tools=c.slide_tools,
    )

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
    c = get_container(ctx)
    sid = UUID(session_id)
    params = _slide_params_from_cli(
        sample_interval=sample_interval,
        threshold=threshold,
        min_interval=min_interval,
        max_candidates=max_candidates,
        settings=c.settings,
    )
    svc = SlidePreviewService(
        settings=c.settings,
        sessions=c.sessions,
        media=c.media_importer,
        slide_tools=c.slide_tools,
    )

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
