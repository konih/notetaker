from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from live_meeting_transcriber.ui.state.model import DiarizationStatus, SessionRowState, TranscriptionStatus

# --- Actions (typed, immutable dataclasses) ---


@dataclass(frozen=True)
class AppStarted:
    at: datetime


@dataclass(frozen=True)
class SettingsLoaded:
    transcription_provider: str
    transcription_model: str
    summarization_provider: str
    summary_model: str
    database_url: str
    audio_chunk_seconds: int
    audio_sample_rate: int
    audio_channels: int
    diarization_enabled: bool
    diarization_provider: str
    log_file_resolved: str
    at: datetime


@dataclass(frozen=True)
class RecordingStartRequested:
    title: str
    audio_source: str | None
    at: datetime


@dataclass(frozen=True)
class RecordingStarted:
    session_id: UUID
    title: str
    audio_source: str
    chunk_seconds: int
    at: datetime


@dataclass(frozen=True)
class RecordingStopRequested:
    at: datetime


@dataclass(frozen=True)
class RecordingStopped:
    at: datetime


@dataclass(frozen=True)
class RecordingFailed:
    message: str
    at: datetime


@dataclass(frozen=True)
class AudioSourceChanged:
    source: str
    at: datetime


@dataclass(frozen=True)
class TranscriptSegmentReceived:
    segment_id: str
    session_id: str
    started_at: datetime
    ended_at: datetime
    text: str
    speaker: str
    at: datetime


@dataclass(frozen=True)
class DiarizationSegmentReceived:
    """Segment after diarization (e.g. speaker label refined)."""

    segment_id: str
    speaker: str
    at: datetime


@dataclass(frozen=True)
class SpeakerAliasUpdated:
    speaker_key: str
    alias: str
    at: datetime


@dataclass(frozen=True)
class ErrorRaised:
    message: str
    at: datetime


@dataclass(frozen=True)
class ErrorAcknowledged:
    error_id: str
    at: datetime


@dataclass(frozen=True)
class WarningRaised:
    message: str
    at: datetime


@dataclass(frozen=True)
class SettingsScreenOpened:
    at: datetime


@dataclass(frozen=True)
class SettingsScreenClosed:
    at: datetime


@dataclass(frozen=True)
class SessionsRefreshRequested:
    at: datetime


@dataclass(frozen=True)
class SessionsListLoaded:
    rows: tuple[SessionRowState, ...]
    at: datetime


@dataclass(frozen=True)
class SessionsScreenOpened:
    at: datetime


@dataclass(frozen=True)
class SessionsScreenClosed:
    at: datetime


@dataclass(frozen=True)
class SessionTitleCommitRequested:
    session_id: UUID
    new_title: str
    at: datetime


@dataclass(frozen=True)
class SessionTitleUpdated:
    session_id: UUID
    title: str
    at: datetime


@dataclass(frozen=True)
class TranscriptionStatusChanged:
    status: TranscriptionStatus
    at: datetime


@dataclass(frozen=True)
class DiarizationStatusChanged:
    status: DiarizationStatus
    at: datetime


@dataclass(frozen=True)
class AudioLevelUpdated:
    """Optional level meter (0..1); None clears."""

    level: float | None
    at: datetime


Action = (
    AppStarted
    | SettingsLoaded
    | RecordingStartRequested
    | RecordingStarted
    | RecordingStopRequested
    | RecordingStopped
    | RecordingFailed
    | AudioSourceChanged
    | TranscriptSegmentReceived
    | DiarizationSegmentReceived
    | SpeakerAliasUpdated
    | ErrorRaised
    | ErrorAcknowledged
    | WarningRaised
    | SettingsScreenOpened
    | SettingsScreenClosed
    | SessionsRefreshRequested
    | SessionsListLoaded
    | SessionsScreenOpened
    | SessionsScreenClosed
    | SessionTitleCommitRequested
    | SessionTitleUpdated
    | TranscriptionStatusChanged
    | DiarizationStatusChanged
    | AudioLevelUpdated
)
