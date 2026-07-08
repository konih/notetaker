"""U6 — the Settings view is grouped by user task and free of internal/legacy jargon."""

from __future__ import annotations

from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.tui.settings_view import build_settings_sections


def _state(**updates: object):
    return initial_app_state().model_copy(update=updates)


def _all_text(sections: list[tuple[str, list[str]]]) -> str:
    parts: list[str] = []
    for title, lines in sections:
        parts.append(title)
        parts.extend(lines)
    return "\n".join(parts)


def test_settings_sections_have_no_internal_or_legacy_jargon() -> None:
    text = _all_text(build_settings_sections(_state())).lower()
    for forbidden in ("diarization", "pyannote", "dual_path", "legacy", "hf_token"):
        assert forbidden not in text, f"jargon leaked into settings view: {forbidden!r}"


def test_settings_sections_are_grouped_by_user_task() -> None:
    sections = build_settings_sections(_state())
    titles = {title for title, _ in sections}
    # Grouped, scannable, user-task-oriented headers.
    assert {"Transcription", "Summaries", "Audio"} <= titles
    # Every section carries at least one line.
    assert all(lines for _title, lines in sections)


def test_settings_sections_render_configured_values() -> None:
    sections = build_settings_sections(
        _state(
            transcription_provider="openai",
            transcription_model="gpt-4o-transcribe",
            audio_include_microphone=False,
            audio_channels=2,
            database_url="sqlite:////tmp/x.db",
        )
    )
    text = _all_text(sections)
    assert "gpt-4o-transcribe" in text
    assert "sqlite:////tmp/x.db" in text
    # Microphone-off is surfaced in plain language.
    assert "off" in text.lower()
