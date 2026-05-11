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
    at: datetime


@dataclass(frozen=True)
class AudioChunkCaptured:
    session_id: UUID
    chunk_id: UUID
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
class TranscriptSegmentPersisted:
    segment: TranscriptSegment
    at: datetime


@dataclass(frozen=True)
class DiarizationChunkCompleted:
    """Fired after diarization runs on a segment (noop or real)."""

    segment: TranscriptSegment
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
    | TranscriptionChunkStarted
    | TranscriptionChunkCompleted
    | TranscriptSegmentPersisted
    | DiarizationChunkCompleted
    | RecordingStopRequested
    | RecordingStopped
    | RecordingFailed
)
