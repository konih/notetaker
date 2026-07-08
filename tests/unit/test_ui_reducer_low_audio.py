from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.reducer import (
    _EMPTY_CHUNKS_WARN_THRESHOLD,
    reduce,
)


def _t() -> datetime:
    return datetime(2026, 5, 11, 12, 0, 0)


def _empty(state):
    return reduce(state, act.TranscriptionChunkEmptyObserved(at=_t()))


def test_repeated_empty_chunks_warn_once_about_low_audio() -> None:
    state = initial_app_state()
    # Below threshold: counts up, no warning yet.
    for _ in range(_EMPTY_CHUNKS_WARN_THRESHOLD - 1):
        state = _empty(state)
    assert state.warnings == ()
    assert state.consecutive_empty_chunks == _EMPTY_CHUNKS_WARN_THRESHOLD - 1

    # Crossing the threshold raises exactly one warning.
    state = _empty(state)
    assert len(state.warnings) == 1
    assert "No speech detected" in state.warnings[0]
    assert state.low_audio_warning_shown is True

    # Further empties do not spam more warnings.
    state = _empty(state)
    state = _empty(state)
    assert len(state.warnings) == 1


def test_real_segment_resets_empty_chunk_counter() -> None:
    state = initial_app_state()
    for _ in range(_EMPTY_CHUNKS_WARN_THRESHOLD - 1):
        state = _empty(state)
    assert state.consecutive_empty_chunks == _EMPTY_CHUNKS_WARN_THRESHOLD - 1

    state = reduce(
        state,
        act.TranscriptSegmentReceived(
            segment_id=str(uuid4()),
            session_id=str(uuid4()),
            started_at=_t(),
            ended_at=_t(),
            text="hello",
            speaker="unknown",
            at=_t(),
        ),
    )
    assert state.consecutive_empty_chunks == 0
    assert state.warnings == ()


def test_recording_started_resets_low_audio_state() -> None:
    state = initial_app_state()
    for _ in range(_EMPTY_CHUNKS_WARN_THRESHOLD):
        state = _empty(state)
    assert state.low_audio_warning_shown is True

    state = reduce(
        state,
        act.RecordingStarted(
            session_id=uuid4(),
            title="New meeting",
            audio_source=":1",
            microphone_source=":3",
            chunk_seconds=10,
            at=_t(),
        ),
    )
    assert state.consecutive_empty_chunks == 0
    assert state.low_audio_warning_shown is False
