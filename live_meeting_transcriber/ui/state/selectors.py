from __future__ import annotations

from datetime import tzinfo

from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    TranscriptionStatus,
    TranscriptLineState,
    UiErrorState,
)
from live_meeting_transcriber.utils.time import format_clock


def select_header_title(state: AppState) -> str:
    base = state.session_title or "No session"
    if state.recording_status == RecordingStatus.recording:
        return f"⏺ {base}"
    if state.recording_status == RecordingStatus.starting:
        return f"◯ {base}"
    if state.recording_status == RecordingStatus.stopping:
        return f"⏹ {base}"
    return base


def select_level_bar(state: AppState, width: int = 12) -> str:
    """ASCII level meter from last chunk peak (updates each chunk, not sample-accurate)."""
    level = state.current_level_meter
    if level is None:
        return "—"
    filled = min(width, max(0, round(level * width)))
    return f"{'█' * filled}{'░' * (width - filled)}"


def select_is_recording(state: AppState) -> bool:
    return state.recording_status == RecordingStatus.recording


def select_unacknowledged_errors(state: AppState) -> tuple[UiErrorState, ...]:
    return tuple(e for e in state.recent_errors if not e.acknowledged)


def select_display_speaker(state: AppState, speaker_key: str) -> str:
    return format_transcript_speaker_label(speaker_key, state.speaker_aliases)


def select_transcript_timestamp(line: TranscriptLineState, tz: tzinfo | None = None) -> str:
    """Compact local wall-clock start time (``HH:MM:SS``) for a transcript line.

    Replaces the full ISO ``started → ended`` range that ate transcript width and
    truncated speech. Start time alone is enough to place a line in the meeting.
    """
    return format_clock(line.started_at, tz)


_RECORDING_LABELS = {
    RecordingStatus.recording: "● Recording",
    RecordingStatus.starting: "◯ Starting…",
    RecordingStatus.stopping: "■ Stopping…",
    RecordingStatus.stopped: "Stopped",
    RecordingStatus.failed: "Recording failed",
    RecordingStatus.idle: "Idle",
}


def _speakers_label(state: AppState) -> str:
    """Plain-language description of how live audio is captured for speaker separation."""
    if state.audio_channels >= 2:
        if state.audio_stereo_mode.strip().lower() == "dual_path":
            return "Speaker split: you vs. remote"
        return "Stereo (mixed)"
    return "Single channel"


def select_status_line(state: AppState) -> str:
    """One-line, plain-language recording status for the Live sidebar.

    Speaks the user's language, not the code's: no ``rec=``/``asr=``/``live_spk=``/``diar_ui=``
    internal keys. Detected speakers ("heard") and audio source are intentionally *not*
    repeated here — they have dedicated sidebar lines, so surfacing them again would duplicate.
    """
    parts = [_RECORDING_LABELS.get(state.recording_status, "Idle")]

    ts = state.transcription_status
    if ts == TranscriptionStatus.active:
        parts.append("transcribing")
    elif ts == TranscriptionStatus.degraded:
        parts.append("transcription degraded")
    elif ts == TranscriptionStatus.failed:
        parts.append("transcription failed")

    parts.append(_speakers_label(state))
    return " · ".join(parts)
