from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.audio.session_recording import (
    full_session_wav_path,
    session_audio_dir,
)
from live_meeting_transcriber.audio.timeline import AudioTimelineEntry, load_timeline
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import TranscriptSegment


def _finalize_load_inputs(
    *, container: Container, settings: Settings, session_id: UUID
) -> tuple[datetime, Path, list[AudioTimelineEntry]]:
    """Read session + paths on the caller's thread (required for SQLite thread affinity)."""
    session = container.sessions.get(session_id)
    if session is None:
        raise KeyError(f"Unknown session {session_id}")
    root = session_audio_dir(settings.ensure_data_dir(), session_id)
    wav = full_session_wav_path(root)
    if not wav.is_file():
        raise FileNotFoundError(
            f"No full_session.wav for this session (nothing recorded yet). Expected: {wav}"
        )
    timeline = load_timeline(root)
    return session.started_at, wav, timeline


def _finalize_persist_segments(
    *, container: Container, session_id: UUID, segments: list[TranscriptSegment]
) -> int:
    container.transcripts.replace_session_transcript(session_id, segments)
    container.diarization_segments.delete_for_session(session_id)
    return len(segments)


def finalize_session_sync(*, container: Container, settings: Settings, session_id: UUID) -> int:
    """Run WhisperX on stored ``full_session.wav`` and replace the session transcript."""
    from live_meeting_transcriber.offline.whisperx_pipeline import run_whisperx_finalize

    session_started_at, wav, timeline = _finalize_load_inputs(
        container=container, settings=settings, session_id=session_id
    )
    segments = run_whisperx_finalize(
        session_id=session_id,
        audio_wav=wav,
        timeline=timeline,
        session_started_at=session_started_at,
        settings=settings,
    )
    return _finalize_persist_segments(container=container, session_id=session_id, segments=segments)


async def finalize_session_offline(
    *,
    container: Container,
    settings: Settings,
    session_id: UUID,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Async entry for the TUI: GPU/CPU work runs in a thread pool; DB stays on the event-loop thread.

    The SQLite connection is created on the asyncio thread; ``check_same_thread`` forbids using it
    from ``asyncio.to_thread`` workers, so only :func:`run_whisperx_finalize` is offloaded.
    """
    from live_meeting_transcriber.offline.whisperx_pipeline import run_whisperx_finalize

    session_started_at, wav, timeline = _finalize_load_inputs(
        container=container, settings=settings, session_id=session_id
    )
    segments = await asyncio.to_thread(
        run_whisperx_finalize,
        session_id=session_id,
        audio_wav=wav,
        timeline=timeline,
        session_started_at=session_started_at,
        settings=settings,
        progress=progress,
    )
    return _finalize_persist_segments(container=container, session_id=session_id, segments=segments)
