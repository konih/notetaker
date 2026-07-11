from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class RecordingStatus(str, Enum):
    idle = "idle"
    starting = "starting"
    recording = "recording"
    stopping = "stopping"
    stopped = "stopped"
    failed = "failed"


class TranscriptionStatus(str, Enum):
    idle = "idle"
    active = "active"
    degraded = "degraded"
    failed = "failed"


class DiarizationStatus(str, Enum):
    disabled = "disabled"
    pending = "pending"
    active = "active"
    degraded = "degraded"
    failed = "failed"


class TranscriptLineState(BaseModel):
    """One line in the live transcript panel (immutable snapshot)."""

    model_config = {"frozen": True}

    id: str
    session_id: str
    started_at: datetime
    ended_at: datetime
    text: str
    speaker: str


class UiErrorState(BaseModel):
    model_config = {"frozen": True}

    id: str
    message: str
    at: datetime
    acknowledged: bool = False


class SessionRowState(BaseModel):
    """One row in the sessions catalog (SQLite-backed)."""

    model_config = {"frozen": True}

    id: str
    title: str
    started_at: datetime
    ended_at: datetime | None = None


class AppState(BaseModel):
    """Immutable UI state snapshot (replace via reducer only)."""

    model_config = {"frozen": True}

    current_session_id: UUID | None = None
    session_title: str | None = None
    recording_status: RecordingStatus = RecordingStatus.idle
    transcription_status: TranscriptionStatus = TranscriptionStatus.idle
    diarization_status: DiarizationStatus = DiarizationStatus.disabled
    audio_source: str | None = None
    microphone_source: str | None = None
    # User-selected mic device (persisted, applied on next recording). Distinct from
    # ``microphone_source`` which is the mic of the *active* recording (cleared on stop).
    configured_microphone_source: str | None = None
    audio_include_microphone: bool = True
    chunk_seconds: int = 10
    transcription_provider: str = "openai"
    transcription_model: str = ""
    summarization_provider: str = "openai"
    summary_model: str = ""
    audio_stereo_mode: str = "mixdown"
    diarization_enabled: bool = False
    diarization_provider: str = "noop"
    finalize_on_session_stop: bool = False
    whisperx_model: str = ""
    whisperx_skip_alignment: bool = False
    hf_token_configured: bool = False
    database_url: str = ""
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    log_file_path: str = ""
    sessions_catalog: tuple[SessionRowState, ...] = Field(default_factory=tuple)
    sessions_loading: bool = False
    recent_transcript_segments: tuple[TranscriptLineState, ...] = Field(default_factory=tuple)
    recent_errors: tuple[UiErrorState, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    notices: tuple[str, ...] = Field(default_factory=tuple)
    speaker_aliases: dict[str, str] = Field(default_factory=dict)
    diarization_detected_speakers: frozenset[str] = frozenset()
    current_level_meter: float | None = None
    # Wall-clock time the current_level_meter peak was captured; drives the U13 decay so the
    # meter falls off between per-chunk updates instead of freezing on a stale peak. None when idle.
    last_level_at: datetime | None = None
    # Recent per-chunk level peaks (oldest → newest, capped), feeding the status-deck
    # sparkline. Reset when a new recording starts so the graph shows this session only.
    level_history: tuple[float, ...] = Field(default_factory=tuple)
    # Wall-clock start of the *current* recording segment; drives the live elapsed timer.
    # Set on RecordingStarted (resets on resume), cleared on stop/failure. None when idle.
    recording_started_at: datetime | None = None
    consecutive_empty_chunks: int = 0
    # --- Per-chunk transcription progress (F8). True between a chunk entering the
    # live transcriber and its completion (incl. empty/failed); the counter also
    # advances on silence-skipped chunks so quiet stretches don't read as a stall.
    chunk_processing: bool = False
    chunks_processed: int = 0
    low_audio_warning_shown: bool = False
    last_updated_at: datetime | None = None
    settings_screen_open: bool = False
    sessions_screen_open: bool = False
    pending_meeting_detail_reload: UUID | None = None
    ui_log_lines: tuple[str, ...] = Field(default_factory=tuple)
    # --- Offline Speaker ID / finalize job feedback (B7). One job runs at a time
    # (sequential queue in TuiController); these fields drive the always-visible
    # status-deck strip so the operator sees start/progress/completion on every
    # tab, not just the Live sidebar or the hidden Logs tab.
    finalize_active_session_id: UUID | None = None
    finalize_active_title: str | None = None
    finalize_stage: str | None = None
    # Monotonic high-water mark into FINALIZE_STAGES for the running job (F8):
    # the reducer only ever raises it, so late/unrecognized progress wording
    # (e.g. the terminal "WhisperX pass complete…") can never run the bar backwards.
    finalize_stage_index: int = 0
    finalize_queued_count: int = 0
    # Last completed/failed job outcome; persists in the deck until the next job
    # starts (a 3s toast is not enough feedback for a multi-minute job).
    finalize_last_result: str | None = None
    finalize_last_result_level: str = "info"


def initial_app_state() -> AppState:
    return AppState()
