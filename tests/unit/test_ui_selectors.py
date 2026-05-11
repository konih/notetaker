from __future__ import annotations

from uuid import uuid4

from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus, UiErrorState
from live_meeting_transcriber.ui.state.selectors import (
    select_display_speaker,
    select_header_title,
    select_is_recording,
    select_unacknowledged_errors,
)
from live_meeting_transcriber.utils.time import utc_now


def test_select_header_title_uses_session_title() -> None:
    s = AppState(session_title="Sync")
    assert select_header_title(s) == "Sync"


def test_select_is_recording() -> None:
    assert select_is_recording(AppState(recording_status=RecordingStatus.recording)) is True
    assert select_is_recording(AppState(recording_status=RecordingStatus.idle)) is False


def test_select_unacknowledged_errors() -> None:
    e1 = UiErrorState(id="1", message="a", at=utc_now(), acknowledged=False)
    e2 = UiErrorState(id="2", message="b", at=utc_now(), acknowledged=True)
    s = AppState(recent_errors=(e1, e2))
    assert [e.id for e in select_unacknowledged_errors(s)] == ["1"]


def test_select_display_speaker_alias() -> None:
    s = AppState(speaker_aliases={"speaker_1": "Alice"})
    assert select_display_speaker(s, "speaker_1") == "Alice"
    assert select_display_speaker(s, "speaker_2") == "speaker_2"


def test_select_header_fallback_uuid_session() -> None:
    sid = uuid4()
    s = AppState(current_session_id=sid, session_title=None)
    assert select_header_title(s) == "No session"
