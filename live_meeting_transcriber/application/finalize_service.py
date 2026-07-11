from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.session_audio import (
    AudioTimelineEntry,
    finalize_unrecoverable_marker_path,
    full_session_wav_path,
    session_audio_dir,
)


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


def _session_dir_no_mkdir(data_dir: Path, session_id: UUID) -> Path:
    # Build the path directly (do not use ``session_audio_dir`` — it mkdirs as a side effect).
    return data_dir / "sessions" / str(session_id)


def _has_full_session_wav(data_dir: Path, session_id: UUID) -> bool:
    return full_session_wav_path(_session_dir_no_mkdir(data_dir, session_id)).is_file()


@dataclass(frozen=True)
class FinalizeUnrecoverableMarker:
    """Durable "finalize failed unrecoverably — stop auto-retrying" record (B3).

    A plain JSON sidecar next to the session's ``full_session.wav`` so an operator
    can ``cat`` or delete it by hand. Startup recovery skips marked sessions; the
    explicit ``finalize-pending`` CLI ignores it (explicit intent beats the marker);
    any later successful finalize clears it.
    """

    cause: str
    error: str
    marked_at: str


def classify_unrecoverable_finalize_error(exc: BaseException, *, session_ended: bool) -> str | None:
    """Human-readable cause when retrying finalize at launch cannot help, else ``None``.

    Deliberately conservative: auth/licence problems (invalid HF token, gated
    pyannote model), network blips and OOM all reach the finalize failure handler
    as generic exceptions, and misclassifying a transient failure would silently
    disable startup recovery. Those stay retryable — ``live-transcriber doctor``
    (F9) diagnoses them. Only two failures provably cannot heal by retrying:

    - the whisperx extra is not importable (nothing installs it by itself);
    - an *ended* session's recording is gone (it will not reappear). While still
      recording, a missing WAV just means no chunk has been flushed yet.
    """
    if isinstance(exc, ImportError):
        return "the whisperx extra is not installed (uv sync --extra whisperx)"
    if isinstance(exc, FileNotFoundError) and session_ended:
        return "the recorded audio (full_session.wav) is missing"
    return None


def read_finalize_unrecoverable_marker(
    *, data_dir: Path, session_id: UUID
) -> FinalizeUnrecoverableMarker | None:
    """The session's won't-auto-retry marker, or ``None`` when absent *or corrupt*.

    A mangled marker fails open (treated as unmarked): the worst case is one more
    retry per launch, whereas failing closed could disable recovery forever.
    """
    path = finalize_unrecoverable_marker_path(_session_dir_no_mkdir(data_dir, session_id))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return FinalizeUnrecoverableMarker(
            cause=str(raw["cause"]),
            error=str(raw.get("error", "")),
            marked_at=str(raw.get("marked_at", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def mark_finalize_unrecoverable(
    *, data_dir: Path, session_id: UUID, cause: str, error: str
) -> None:
    root = _session_dir_no_mkdir(data_dir, session_id)
    root.mkdir(parents=True, exist_ok=True)
    payload = {"cause": cause, "error": error, "marked_at": datetime.now(UTC).isoformat()}
    finalize_unrecoverable_marker_path(root).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def clear_finalize_unrecoverable_marker(*, data_dir: Path, session_id: UUID) -> None:
    finalize_unrecoverable_marker_path(_session_dir_no_mkdir(data_dir, session_id)).unlink(
        missing_ok=True
    )


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
    timeline = container.session_audio.load_timeline(root)
    return session.started_at, wav, timeline


def _finalize_persist_segments(
    *, container: Container, session_id: UUID, segments: list[TranscriptSegment]
) -> int:
    container.transcripts.replace_session_transcript(session_id, segments)
    container.diarization_segments.delete_for_session(session_id)
    return len(segments)


def finalize_session_sync(*, container: Container, settings: Settings, session_id: UUID) -> int:
    """Run offline ASR on stored ``full_session.wav`` and replace the session transcript."""
    session_started_at, wav, timeline = _finalize_load_inputs(
        container=container, settings=settings, session_id=session_id
    )
    segments = container.offline_transcriber().transcribe_session(
        session_id=session_id,
        audio_wav=wav,
        timeline=timeline,
        session_started_at=session_started_at,
    )
    n = _finalize_persist_segments(container=container, session_id=session_id, segments=segments)
    # Finalize worked — the cause behind any won't-auto-retry marker is gone (B3).
    clear_finalize_unrecoverable_marker(data_dir=settings.ensure_data_dir(), session_id=session_id)
    return n


async def finalize_session_offline(
    *,
    container: Container,
    settings: Settings,
    session_id: UUID,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Async entry for the TUI: GPU/CPU work runs in a thread pool; DB stays on the event-loop thread.

    The SQLite connection is created on the asyncio thread; ``check_same_thread`` forbids using it
    from ``asyncio.to_thread`` workers, so only the offline transcription is offloaded.
    """
    from live_meeting_transcriber.utils.std_streams import subprocess_safe_std_streams

    session_started_at, wav, timeline = _finalize_load_inputs(
        container=container, settings=settings, session_id=session_id
    )
    offline_transcriber = container.offline_transcriber()

    def _run() -> list[TranscriptSegment]:
        # A running TUI redirects std streams to fileno()==-1; WhisperX's model load forks a
        # child and would raise "bad value(s) in fds_to_keep". Give it real (devnull) std fds.
        with subprocess_safe_std_streams():
            return offline_transcriber.transcribe_session(
                session_id=session_id,
                audio_wav=wav,
                timeline=timeline,
                session_started_at=session_started_at,
                progress=progress,
            )

    segments = await asyncio.to_thread(_run)
    n = _finalize_persist_segments(container=container, session_id=session_id, segments=segments)
    # Finalize worked — the cause behind any won't-auto-retry marker is gone (B3).
    clear_finalize_unrecoverable_marker(data_dir=settings.ensure_data_dir(), session_id=session_id)
    return n
