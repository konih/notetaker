from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.audio.session_recording import (
    full_session_wav_path,
    session_audio_dir,
)
from live_meeting_transcriber.audio.timeline import AudioTimelineEntry, load_timeline
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment


def _as_utc(dt: datetime) -> datetime:
    """Coerce a datetime to tz-aware UTC. A pre-existing DB can mix naive (old) and
    aware (post-A1) ``ended_at`` rows (see roadmap A11); comparing the two raises. Treat
    naive values as UTC — which is what the app has always written — so the recovery
    window comparison never throws."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def find_unfinalized_sessions(
    *,
    container: Container,
    ended_after: datetime | None = None,
    include_interrupted: bool = False,
    data_dir: Path | None = None,
    exclude_session_id: UUID | None = None,
) -> list[MeetingSession]:
    """Sessions with a transcript where every segment is still ``"unknown"``.

    A reliable-enough proxy for "recorded but finalize (WhisperX + diarization)
    never actually completed" — e.g. an auto-finalize-on-stop task that got
    killed by the app exiting before it finished. ``ended_after`` bounds the
    scan to recently-ended sessions (avoids repeatedly reprocessing sessions
    that legitimately have no distinguishable speakers).

    By default only *ended* sessions are considered. A meeting whose recording
    was interrupted (app crash / force-quit) never got ``ended_at`` set, so it
    looks like it is still recording and would otherwise be stuck all-``unknown``
    forever even though its ``full_session.wav`` survives on disk. Pass
    ``include_interrupted=True`` (with ``data_dir``) to also surface those — but
    only when their recording actually exists, and never ``exclude_session_id``
    (the session the user is actively recording right now).
    """
    cutoff = _as_utc(ended_after) if ended_after is not None else None
    resolved_data_dir = data_dir
    if include_interrupted and resolved_data_dir is None and container.settings is not None:
        resolved_data_dir = container.settings.ensure_data_dir()

    out: list[MeetingSession] = []
    for session in container.sessions.list():
        if exclude_session_id is not None and session.id == exclude_session_id:
            continue
        if session.ended_at is None:
            # Interrupted (never marked ended). Only recoverable if opted in and the
            # recording survives; otherwise it's genuinely still recording — skip.
            if not include_interrupted or resolved_data_dir is None:
                continue
            if not _has_full_session_wav(resolved_data_dir, session.id):
                continue
        elif cutoff is not None and _as_utc(session.ended_at) < cutoff:
            continue
        segments = container.transcripts.list_by_session(session.id)
        if not segments:
            continue
        if any(s.speaker != "unknown" for s in segments):
            continue
        out.append(session)
    return out


def _has_full_session_wav(data_dir: Path, session_id: UUID) -> bool:
    # Build the path directly (do not use ``session_audio_dir`` — it mkdirs as a side effect).
    return full_session_wav_path(data_dir / "sessions" / str(session_id)).is_file()


def session_speakers_are_all_unknown(*, container: Container, session_id: UUID) -> bool:
    """True if the session has a transcript but *no* segment carries a real speaker label.

    After a finalize run this means diarization did not actually label anyone — WhisperX
    refined the words but pyannote was skipped (no ``HF_TOKEN``) or produced nothing. Callers
    use it to tell the operator *why* their meeting still shows "unknown" instead of silently
    reporting success.
    """
    segments = container.transcripts.list_by_session(session_id)
    return bool(segments) and all(s.speaker == "unknown" for s in segments)


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
    from live_meeting_transcriber.utils.std_streams import subprocess_safe_std_streams

    session_started_at, wav, timeline = _finalize_load_inputs(
        container=container, settings=settings, session_id=session_id
    )

    def _run() -> list[TranscriptSegment]:
        # A running TUI redirects std streams to fileno()==-1; WhisperX's model load forks a
        # child and would raise "bad value(s) in fds_to_keep". Give it real (devnull) std fds.
        with subprocess_safe_std_streams():
            return run_whisperx_finalize(
                session_id=session_id,
                audio_wav=wav,
                timeline=timeline,
                session_started_at=session_started_at,
                settings=settings,
                progress=progress,
            )

    segments = await asyncio.to_thread(_run)
    return _finalize_persist_segments(container=container, session_id=session_id, segments=segments)
