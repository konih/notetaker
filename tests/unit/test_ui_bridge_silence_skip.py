"""F1: a silence-skipped chunk must not look like a stall or an error in the TUI."""

from __future__ import annotations

from uuid import uuid4

from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import TranscriptionStatus
from live_meeting_transcriber.utils.time import utc_now


def test_bridge_silence_skip_keeps_status_active_without_warning() -> None:
    actions = application_events_to_actions(
        ev.AudioChunkSkippedSilent(
            session_id=uuid4(), chunk_id=uuid4(), rms_dbfs=-85.0, at=utc_now()
        )
    )
    # No warning: skipping silence is normal operation, not a fault.
    assert not any(isinstance(a, act.WarningRaised) for a in actions)
    # Status stays active so a run of quiet chunks does not read as a stall.
    statuses = [a for a in actions if isinstance(a, act.TranscriptionStatusChanged)]
    assert statuses and all(a.status is TranscriptionStatus.active for a in statuses)
    # It feeds the same empty-chunk counter, so sustained silence still surfaces
    # the existing low-audio/misrouted-source hint.
    assert any(isinstance(a, act.TranscriptionChunkEmptyObserved) for a in actions)
