from __future__ import annotations

from datetime import tzinfo

from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
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


def select_status_line(state: AppState) -> str:
    rec = state.recording_status.value
    if state.recording_status == RecordingStatus.recording:
        rec = "● recording"
    elif state.recording_status == RecordingStatus.starting:
        rec = "◯ starting"
    elif state.recording_status == RecordingStatus.stopping:
        rec = "■ stopping"
    if state.audio_channels >= 2:
        live_spk = (
            "dual" if state.audio_stereo_mode.strip().lower() == "dual_path" else "mixdown→unknown"
        )
    else:
        live_spk = "mono"
    parts = [
        f"rec={rec}",
        f"asr={state.transcription_status.value}",
        f"live_spk={live_spk}",
        f"diar_ui={state.diarization_status.value}",
    ]
    if state.finalize_on_session_stop:
        parts.append("auto_finalize")
    if state.diarization_detected_speakers:
        parts.append(f"heard={','.join(sorted(state.diarization_detected_speakers))}")
    if state.audio_source:
        parts.append(f"src={state.audio_source}")
    return " | ".join(parts)
