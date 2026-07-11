"""``record`` command — live system-audio capture into a session."""

from __future__ import annotations

import asyncio

import typer

from live_meeting_transcriber.application.dual_path import dual_path_downgrade_reason
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.audio.sources import resolve_microphone_source
from live_meeting_transcriber.cli.deps import _end_session_safely, get_container
from live_meeting_transcriber.observability.logging import get_logger


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
    c = get_container(ctx)
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
    dual_path_reason = dual_path_downgrade_reason(
        audio_stereo_mode=c.settings.audio_stereo_mode,
        audio_channels=c.settings.audio_channels,
        transcriber=c.transcriber,
    )
    if dual_path_reason is not None:
        typer.echo(f"Warning: {dual_path_reason}", err=True)
        log.warning("dual_path_downgrade", message=dual_path_reason)

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
        silence_skip_enabled=c.settings.audio_silence_skip_enabled,
        silence_threshold_dbfs=c.settings.audio_silence_threshold_dbfs,
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
