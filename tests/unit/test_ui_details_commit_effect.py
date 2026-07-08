from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.utils.time import utc_now


def _controller(store: Store, sessions: MagicMock) -> TuiController:
    container = MagicMock()
    container.sessions = sessions
    return TuiController(store=store, container=container, settings=MagicMock())


async def test_session_details_commit_persists_all_fields_and_refreshes_live_title() -> None:
    sid = uuid4()
    state = initial_app_state().model_copy(
        update={"current_session_id": sid, "session_title": "Meeting 2026-07-08"}
    )
    store = Store(state=state)
    sessions = MagicMock()
    sessions.update_details.return_value = MeetingSession(
        id=sid, title="Weekly standup", notes="Agenda: roadmap", attendees=["Alice", "Bob"]
    )
    controller = _controller(store, sessions)

    await controller.handle(
        store,
        act.SessionDetailsCommitRequested(
            session_id=sid,
            title="Weekly standup",
            notes="Agenda: roadmap",
            attendees=["Alice", "Bob"],
            at=utc_now(),
        ),
    )

    sessions.update_details.assert_called_once_with(
        sid, title="Weekly standup", notes="Agenda: roadmap", attendees=["Alice", "Bob"]
    )
    # The existing SessionTitleUpdated path refreshes the live header title for free.
    assert store.get_state().session_title == "Weekly standup"


async def test_session_details_commit_rejects_empty_title() -> None:
    sid = uuid4()
    store = Store(state=initial_app_state())
    sessions = MagicMock()
    controller = _controller(store, sessions)

    await controller.handle(
        store,
        act.SessionDetailsCommitRequested(
            session_id=sid, title="   ", notes="x", attendees=[], at=utc_now()
        ),
    )

    sessions.update_details.assert_not_called()
    assert store.get_state().recent_errors, "empty title should raise a user-visible error"


async def test_session_details_commit_missing_session_raises_error() -> None:
    sid = uuid4()
    store = Store(state=initial_app_state())
    sessions = MagicMock()
    sessions.update_details.return_value = None
    controller = _controller(store, sessions)

    await controller.handle(
        store,
        act.SessionDetailsCommitRequested(
            session_id=sid, title="Title", notes="", attendees=[], at=utc_now()
        ),
    )

    assert store.get_state().recent_errors, "missing session should raise a user-visible error"
