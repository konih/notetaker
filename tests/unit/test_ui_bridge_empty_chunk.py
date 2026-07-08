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
    # No immediate warning (a single empty chunk is normal silence)...
    assert not any(isinstance(a, act.WarningRaised) for a in actions)
    assert any(isinstance(a, act.TranscriptionStatusChanged) for a in actions)
    # ...but it is observed so the reducer can warn after repeated empties.
    assert any(isinstance(a, act.TranscriptionChunkEmptyObserved) for a in actions)


def test_bridge_transcription_unavailable_raises_warning() -> None:
    sid = uuid4()
    actions = application_events_to_actions(
        ev.TranscriptionUnavailable(session_id=sid, message="model failed to load", at=utc_now())
    )
    warnings = [a for a in actions if isinstance(a, act.WarningRaised)]
    assert len(warnings) == 1
    assert "model failed to load" in warnings[0].message
