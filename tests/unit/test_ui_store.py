from __future__ import annotations

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.utils.time import utc_now


def test_store_subscribe_sees_dispatch_updates() -> None:
    store = Store()
    seen: list[str] = []

    def on_change(state: AppState) -> None:
        seen.append(state.recording_status.value)

    store.subscribe(on_change)
    store.dispatch(act.RecordingStartRequested(title="x", audio_source=None, at=utc_now()))
    assert seen[-1] == RecordingStatus.starting.value
