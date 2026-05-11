from __future__ import annotations

from uuid import uuid4

from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.utils.time import utc_now


def test_bridge_transcription_chunk_empty_is_silent_no_warning() -> None:
    sid = uuid4()
    cid = uuid4()
    actions = application_events_to_actions(
        ev.TranscriptionChunkEmpty(session_id=sid, chunk_id=cid, at=utc_now())
    )
    assert not any(isinstance(a, act.WarningRaised) for a in actions)
    assert any(isinstance(a, act.TranscriptionStatusChanged) for a in actions)
