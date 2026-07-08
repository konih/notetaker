from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from live_meeting_transcriber.ui.state.model import (
    DiarizationStatus,
    SessionRowState,
    TranscriptionStatus,
    TranscriptLineState,
)

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
    audio_stereo_mode: str
    diarization_enabled: bool
    diarization_provider: str
    finalize_on_session_stop: bool
    whisperx_model: str
    whisperx_skip_alignment: bool
    hf_token_configured: bool
    log_file_resolved: str
    audio_include_microphone: bool
    at: datetime


@dataclass(frozen=True)
class RecordingStartRequested:
    """Start capture. If ``resume_session_id`` is set, append to that meeting instead of creating one."""

    title: str
    audio_source: str | None
    at: datetime
    resume_session_id: UUID | None = None
    microphone_source: str | None = None


@dataclass(frozen=True)
class RecordingStarted:
    session_id: UUID
    title: str
    audio_source: str
    microphone_source: str | None
    chunk_seconds: int
    at: datetime
    resumed: bool = False
    loaded_transcript_segments: tuple[TranscriptLineState, ...] = ()


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
class SpeakerAliasesLoaded:
    """Replace in-session alias map (e.g. from SQLite when recording starts)."""

    aliases: dict[str, str]
    at: datetime


@dataclass(frozen=True)
class DiarizationSpeakersDetected:
    """Union of diarization speaker keys seen so far in the live session."""

    speakers: frozenset[str]
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
class NoticeRaised:
    """Non-error status for the UI (export path, summary done, etc.)."""

    message: str
    at: datetime


@dataclass(frozen=True)
class UiLogLineAdded:
    """Append one line to the Logs tab (and formatted for RichLog markup)."""

    level: str
    message: str
    at: datetime


@dataclass(frozen=True)
class ExportMarkdownRequested:
    """Write session markdown to data_dir/exports (and Obsidian when configured).

    ``session_id`` None means the live recording session from UI state.
    """

    at: datetime
    session_id: UUID | None = None


@dataclass(frozen=True)
class SummarizeSessionRequested:
    """Run summarization for a session and store in DB.

    ``session_id`` None means the live recording session from UI state.
    ``user_context`` is optional one-off guidance for the LLM (not persisted).
    """

    at: datetime
    session_id: UUID | None = None
    user_context: str | None = None


@dataclass(frozen=True)
class FinalizeSessionRequested:
    """Run offline WhisperX + diarization on ``full_session.wav`` for this session."""

    session_id: UUID
    at: datetime


@dataclass(frozen=True)
class FinalizeSessionSucceeded:
    """Finalize replaced the transcript; optionally refresh live transcript panel."""

    session_id: UUID
    segment_count: int
    live_lines: tuple[TranscriptLineState, ...] | None
    at: datetime


@dataclass(frozen=True)
class DetailReloadAcknowledged:
    """Meetings tab consumed ``pending_meeting_detail_reload``."""

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
class SessionDetailsCommitRequested:
    """Persist title/notes/attendees for a session (used to edit the current live meeting)."""

    session_id: UUID
    title: str
    notes: str
    attendees: list[str]
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


@dataclass(frozen=True)
class TranscriptionChunkEmptyObserved:
    """A chunk produced no transcript text; used to detect silent/misrouted audio."""

    at: datetime


@dataclass(frozen=True)
class AudioSourcesSelected:
    """User picked audio devices in the sources menu (persisted, applied next recording).

    ``None`` for a field means "not configured — fall back to defaults".
    """

    monitor_source: str | None
    microphone_source: str | None
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
    | SpeakerAliasesLoaded
    | DiarizationSpeakersDetected
    | ErrorRaised
    | ErrorAcknowledged
    | WarningRaised
    | NoticeRaised
    | UiLogLineAdded
    | ExportMarkdownRequested
    | SummarizeSessionRequested
    | FinalizeSessionRequested
    | FinalizeSessionSucceeded
    | DetailReloadAcknowledged
    | SettingsScreenOpened
    | SettingsScreenClosed
    | SessionsRefreshRequested
    | SessionsListLoaded
    | SessionsScreenOpened
    | SessionsScreenClosed
    | SessionTitleCommitRequested
    | SessionDetailsCommitRequested
    | SessionTitleUpdated
    | TranscriptionStatusChanged
    | DiarizationStatusChanged
    | AudioLevelUpdated
    | TranscriptionChunkEmptyObserved
    | AudioSourcesSelected
)
