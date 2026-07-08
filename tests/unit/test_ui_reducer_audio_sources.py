from __future__ import annotations

from datetime import datetime

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.reducer import reduce


def _t() -> datetime:
    return datetime(2026, 5, 11, 12, 0, 0)


def test_audio_sources_selected_updates_state() -> None:
    state = initial_app_state()
    state = reduce(
        state,
        act.AudioSourcesSelected(monitor_source=":4", microphone_source=":3", at=_t()),
    )
    assert state.audio_source == ":4"
    assert state.configured_microphone_source == ":3"


def test_audio_sources_selected_monitor_only() -> None:
    state = initial_app_state()
    state = reduce(
        state,
        act.AudioSourcesSelected(monitor_source=":4", microphone_source=None, at=_t()),
    )
    assert state.audio_source == ":4"
    assert state.configured_microphone_source is None
