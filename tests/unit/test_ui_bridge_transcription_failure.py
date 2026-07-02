from __future__ import annotations

from uuid import uuid4

from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import TranscriptionStatus
from live_meeting_transcriber.utils.time import utc_now


def test_bridge_transcription_chunk_failed_warns_and_stays_active() -> None:
    sid = uuid4()
    cid = uuid4()
    actions = application_events_to_actions(
        ev.TranscriptionChunkFailed(
            session_id=sid,
            chunk_id=cid,
            message="rate limit",
            at=utc_now(),
        )
    )
    assert any(isinstance(a, act.WarningRaised) for a in actions)
    ts = next(a for a in actions if isinstance(a, act.TranscriptionStatusChanged))
    assert ts.status == TranscriptionStatus.active
