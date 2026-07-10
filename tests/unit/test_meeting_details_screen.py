from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import EditMeetingDetailsScreen, TranscriberApp
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput
from textual.widgets import TextArea


def _app_with_live_session(
    sid: object,
    existing: MeetingSession,
    *,
    detected_speakers: frozenset[str] = frozenset(),
    speaker_aliases: dict[str, str] | None = None,
) -> tuple[TranscriberApp, MagicMock]:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.sessions.get.return_value = existing
    container.sessions.update_details.return_value = existing.model_copy(
        update={"title": "Weekly standup", "notes": "Agenda", "attendees": ["Alice", "Bob"]}
    )
    store = Store(
        state=initial_app_state().model_copy(
            update={
                "current_session_id": sid,
                "session_title": "Meeting 2026-07-08",
                "diarization_detected_speakers": detected_speakers,
                "speaker_aliases": speaker_aliases or {},
            }
        )
    )
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    app = TranscriberApp(store=store, container=container, controller=controller)
    return app, container


async def test_meeting_details_modal_persists_and_refreshes_live_title() -> None:
    # U20 AC1/AC3: editing details for the current live meeting persists title/notes/attendees
    # and the live header title refreshes immediately.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-08")
    app, container = _app_with_live_session(sid, existing)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_meeting_details()
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, EditMeetingDetailsScreen)
        screen.query_one("#details-title", TabCompletableInput).value = "Weekly standup"
        screen.query_one("#details-notes", TextArea).text = "Agenda"
        screen.query_one("#details-attendees", TabCompletableInput).value = "Alice, Bob"
        await screen.action_save()
        await pilot.pause()

    container.sessions.update_details.assert_called_once_with(
        sid, title="Weekly standup", notes="Agenda", attendees=["Alice", "Bob"]
    )
    assert app.store.get_state().session_title == "Weekly standup"


async def test_meeting_details_names_detected_speaker_live() -> None:
    # U20 AC3: naming a detected speaker during the live meeting persists the alias and
    # updates live state so the transcript relabels immediately.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-08")
    app, container = _app_with_live_session(
        sid, existing, detected_speakers=frozenset({"SPEAKER_00", "SPEAKER_01"})
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_meeting_details()
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, EditMeetingDetailsScreen)
        screen.query_one("#details-spk-SPEAKER_00", TabCompletableInput).value = "Alice"
        await screen.action_save()
        await pilot.pause()

    container.session_speakers.replace_map.assert_called_once()
    call_sid, mapping = container.session_speakers.replace_map.call_args[0]
    assert call_sid == sid
    assert mapping["SPEAKER_00"] == "Alice"
    assert app.store.get_state().speaker_aliases["SPEAKER_00"] == "Alice"


def test_edit_meeting_binding_is_discoverably_labelled() -> None:
    # U22: the Live-tab edit affordance is labelled "Edit meeting" (discoverable), not the
    # opaque "Meeting details"; the action name is unchanged for stability.
    from textual.binding import Binding

    bindings = [b for b in TranscriberApp.BINDINGS if isinstance(b, Binding)]
    edit = next(b for b in bindings if b.action == "meeting_details")
    assert edit.key == "t"
    assert edit.description == "Edit meeting"


async def test_meeting_details_empty_speaker_hint_points_to_speaker_id() -> None:
    # U22: with no detected speakers (the default — live diarization is off), the editor explains
    # that naming happens after Speaker ID on the finished meeting, not "once the meeting has audio".
    from textual.widgets import Static

    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-08")
    app, _container = _app_with_live_session(sid, existing, detected_speakers=frozenset())

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_meeting_details()
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, EditMeetingDetailsScreen)
        texts = [str(w.render()) for w in screen.query(Static)]
        hint = next(t for t in texts if "No speakers detected" in t)
        assert "Speaker ID" in hint
        assert "Ctrl+I" in hint


async def test_meeting_details_action_no_session_notifies() -> None:
    # No current session → modal is not opened.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="x")
    app, _container = _app_with_live_session(sid, existing)
    app.store = Store(state=initial_app_state())  # current_session_id is None

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_meeting_details()
        await pilot.pause()
        assert not isinstance(pilot.app.screen, EditMeetingDetailsScreen)
