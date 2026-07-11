"""Redesign — level_history feeds the status-deck sparkline (reducer-owned)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.reducer import _MAX_LEVEL_HISTORY, reduce

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def test_audio_level_appends_to_history_in_order() -> None:
    state = initial_app_state()
    for level in (0.1, 0.5, 0.9):
        state = reduce(state, act.AudioLevelUpdated(level=level, at=_NOW))
    assert state.level_history == (0.1, 0.5, 0.9)
    assert state.current_level_meter == 0.9


def test_level_history_is_capped() -> None:
    state = initial_app_state()
    for i in range(_MAX_LEVEL_HISTORY + 10):
        state = reduce(state, act.AudioLevelUpdated(level=i / 100, at=_NOW))
    assert len(state.level_history) == _MAX_LEVEL_HISTORY
    # Oldest readings fall off the front; the newest is retained.
    assert state.level_history[-1] == (_MAX_LEVEL_HISTORY + 9) / 100


def test_recording_start_resets_history() -> None:
    state = reduce(initial_app_state(), act.AudioLevelUpdated(level=0.7, at=_NOW))
    assert state.level_history
    state = reduce(
        state,
        act.RecordingStarted(
            session_id=uuid4(),
            title="t",
            audio_source="monitor",
            microphone_source=None,
            chunk_seconds=10,
            at=_NOW,
        ),
    )
    assert state.level_history == ()
