"""Session audio layout and timeline model.

The on-disk layout of a session's audio artifacts (``sessions/<id>/full_session.wav``
plus its wall-clock timeline) is a core application concept shared by every layer, so
the *layout* (path computation) and the timeline *value type / mapping math* live in
the domain. Reading and writing those files is adapter work — see the
``SessionAudioStore`` port in :mod:`live_meeting_transcriber.domain.ports` and its
ffmpeg-backed implementation in :mod:`live_meeting_transcriber.audio`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

# OpenAI and most cloud STT APIs reject clips shorter than ~0.1s.
MIN_TRANSCRIPTION_CHUNK_SECONDS = 0.1


@dataclass(frozen=True)
class AudioTimelineEntry:
    """One appended chunk: audio interval in the rolling ``full_session.wav`` and its wall-clock span."""

    audio_start_sec: float
    audio_end_sec: float
    wall_started_at: datetime
    wall_ended_at: datetime


def session_audio_dir(data_dir: Path, session_id: UUID) -> Path:
    """Per-session audio directory. Ensures it exists (idempotent mkdir)."""
    d = (data_dir / "sessions" / str(session_id)).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def full_session_wav_path(session_audio_root: Path) -> Path:
    return session_audio_root / "full_session.wav"


def finalize_unrecoverable_marker_path(session_audio_root: Path) -> Path:
    """Sidecar written when finalize failed *unrecoverably* (B3): startup recovery
    stops re-enqueuing the session until a later successful finalize clears it.
    Pure path math — reading/writing the marker is application-layer work."""
    return session_audio_root / "finalize_unrecoverable.json"


def map_audio_time_to_wall(entries: Sequence[AudioTimelineEntry], t_sec: float) -> datetime:
    """Linearly map a position in the concatenated WAV timeline to wall time."""
    if not entries:
        raise ValueError("timeline is empty")
    if t_sec <= entries[0].audio_start_sec:
        return entries[0].wall_started_at
    if t_sec >= entries[-1].audio_end_sec:
        return entries[-1].wall_ended_at
    for e in entries:
        if t_sec < e.audio_end_sec - 1e-9:
            dur_a = e.audio_end_sec - e.audio_start_sec
            if dur_a <= 1e-9:
                return e.wall_started_at
            frac = (t_sec - e.audio_start_sec) / dur_a
            frac = max(0.0, min(1.0, frac))
            wall_delta = (e.wall_ended_at - e.wall_started_at).total_seconds() * frac
            return e.wall_started_at + timedelta(seconds=wall_delta)
    return entries[-1].wall_ended_at
