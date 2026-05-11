"""Application-level events emitted by use-cases (recorder, session, etc.).

UI and other adapters translate these into their own actions/messages.
Do not import UI code from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from live_meeting_transcriber.domain.models import TranscriptSegment


@dataclass(frozen=True)
class SessionCreated:
    session_id: UUID
    title: str
    at: datetime


@dataclass(frozen=True)
class RecordingPrepareStarted:
    """About to open audio / create session resources."""

    session_id: UUID
    at: datetime


@dataclass(frozen=True)
class RecordingLoopEntered:
    session_id: UUID
    audio_source: str
    chunk_seconds: int
    microphone_source: str | None
    at: datetime


@dataclass(frozen=True)
class AudioChunkCaptured:
    session_id: UUID
    chunk_id: UUID
    at: datetime


@dataclass(frozen=True)
class AudioChunkLevelMeasured:
    """Peak level (0..1) from the captured WAV after each chunk (not real-time)."""

    session_id: UUID
    chunk_id: UUID
    peak_linear: float
    at: datetime


@dataclass(frozen=True)
class TranscriptionChunkStarted:
    session_id: UUID
    chunk_id: UUID
    at: datetime


@dataclass(frozen=True)
class TranscriptionChunkCompleted:
    session_id: UUID
    chunk_id: UUID
    at: datetime


@dataclass(frozen=True)
class TranscriptionChunkEmpty:
    """API returned no text for this chunk; segment was skipped (recording continues)."""

    session_id: UUID
    chunk_id: UUID
    at: datetime


@dataclass(frozen=True)
class TranscriptSegmentPersisted:
    segment: TranscriptSegment
    at: datetime


@dataclass(frozen=True)
class DiarizationChunkCompleted:
    """Fired after diarization runs on a segment (noop or real)."""

    segment: TranscriptSegment
    detected_speakers: frozenset[str]
    at: datetime


@dataclass(frozen=True)
class DiarizationFailed:
    """Non-fatal diarization error (recording continues with unknown / prior speaker)."""

    session_id: UUID
    chunk_id: UUID | None
    message: str
    at: datetime


@dataclass(frozen=True)
class RecordingStopRequested:
    session_id: UUID
    at: datetime


@dataclass(frozen=True)
class RecordingStopped:
    session_id: UUID
    at: datetime


@dataclass(frozen=True)
class RecordingFailed:
    session_id: UUID | None
    message: str
    at: datetime


ApplicationEvent = (
    SessionCreated
    | RecordingPrepareStarted
    | RecordingLoopEntered
    | AudioChunkCaptured
    | AudioChunkLevelMeasured
    | TranscriptionChunkStarted
    | TranscriptionChunkCompleted
    | TranscriptionChunkEmpty
    | TranscriptSegmentPersisted
    | DiarizationChunkCompleted
    | DiarizationFailed
    | RecordingStopRequested
    | RecordingStopped
    | RecordingFailed
)
