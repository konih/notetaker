from __future__ import annotations

from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus, UiErrorState


def select_header_title(state: AppState) -> str:
    if state.session_title:
        return state.session_title
    return "No session"


def select_is_recording(state: AppState) -> bool:
    return state.recording_status == RecordingStatus.recording


def select_unacknowledged_errors(state: AppState) -> tuple[UiErrorState, ...]:
    return tuple(e for e in state.recent_errors if not e.acknowledged)


def select_display_speaker(state: AppState, speaker_key: str) -> str:
    return state.speaker_aliases.get(speaker_key, speaker_key)


def select_status_line(state: AppState) -> str:
    parts = [
        f"rec={state.recording_status.value}",
        f"asr={state.transcription_status.value}",
        f"diar={state.diarization_status.value}",
    ]
    if state.audio_source:
        parts.append(f"src={state.audio_source}")
    return " | ".join(parts)
