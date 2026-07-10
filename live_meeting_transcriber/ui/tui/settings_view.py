"""View-model for the read-only Settings screen (U6).

Groups configuration by user task and keeps the copy in plain language — no
internal/legacy implementation labels (chunk pyannote, DIARIZATION_*, dual_path).
Pure function of :class:`AppState` so it can be unit-tested without a running app.
"""

from __future__ import annotations

from live_meeting_transcriber.ui.state.model import AppState

SettingsSection = tuple[str, list[str]]


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def build_settings_sections(state: AppState) -> list[SettingsSection]:
    """Return grouped, user-facing settings sections as (title, lines)."""
    separate_speakers = state.audio_stereo_mode == "dual_path"

    audio_lines = [
        f"Recording: {state.chunk_seconds}s chunks · {state.audio_sample_rate} Hz "
        f"· {state.audio_channels} channel(s)",
        f"Microphone mix: {_on_off(state.audio_include_microphone)}",
        f"Separate your voice from meeting audio: {_on_off(separate_speakers)}",
    ]

    speaker_lines = [
        f"Label speakers after the meeting: {_on_off(state.finalize_on_session_stop)}",
        f"Speaker model: {state.whisperx_model or '—'}",
        f"Ready to label speakers: {'yes' if state.hf_token_configured else 'no (needs setup)'}",
        "Run now: ctrl+d from Live or Meetings",
    ]

    storage_lines = [
        f"Database: {state.database_url or '—'}",
        f"Log file: {state.log_file_path or '—'}",
        "Errors & finalize progress: Logs tab (ctrl+3)",
    ]

    return [
        (
            "Transcription",
            [f"{state.transcription_provider} · {state.transcription_model or 'default model'}"],
        ),
        (
            "Summaries",
            [f"{state.summarization_provider} · {state.summary_model or 'default model'}"],
        ),
        ("Audio", audio_lines),
        ("Speaker labels", speaker_lines),
        ("Storage & logs", storage_lines),
    ]
