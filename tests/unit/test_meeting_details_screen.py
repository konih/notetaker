from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import NameSpeakersScreen, TranscriberApp
from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput

from tests.unit.conftest import make_tui_app


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
    app = make_tui_app(
        container,
        state_updates={
            "current_session_id": sid,
            "session_title": "Meeting 2026-07-08",
            "diarization_detected_speakers": detected_speakers,
            "speaker_aliases": speaker_aliases or {},
        },
    )
    return app, container


async def test_name_speakers_names_detected_speaker_live() -> None:
    # U20 AC3: naming a detected speaker during the live meeting persists the alias and
    # updates live state so the transcript relabels immediately. Title/notes/attendees now
    # live inline on the Live tab (U23) — this modal is speaker-naming only.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-08")
    app, container = _app_with_live_session(
        sid, existing, detected_speakers=frozenset({"SPEAKER_00", "SPEAKER_01"})
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_name_speakers()
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, NameSpeakersScreen)
        screen.query_one("#details-spk-SPEAKER_00", TabCompletableInput).value = "Alice"
        await screen.action_save()
        await pilot.pause()

    container.session_speakers.replace_map.assert_called_once()
    call_sid, mapping = container.session_speakers.replace_map.call_args[0]
    assert call_sid == sid
    assert mapping["SPEAKER_00"] == "Alice"
    assert app.store.get_state().speaker_aliases["SPEAKER_00"] == "Alice"
    # The modal must NOT write session metadata — that path belongs to the inline fields (U23).
    # A second writer of title/notes/attendees is exactly the clobber this refactor removed.
    container.sessions.update_details.assert_not_called()


def test_name_speakers_binding_is_discoverably_labelled() -> None:
    # U23: the Live-tab `t` affordance now names speakers (title/notes/attendees are inline);
    # it is labelled "Name speakers", bound to the `name_speakers` action.
    from textual.binding import Binding

    bindings = [b for b in TranscriberApp.BINDINGS if isinstance(b, Binding)]
    edit = next(b for b in bindings if b.action == "name_speakers")
    assert edit.key == "t"
    assert edit.description == "Name speakers"


async def test_name_speakers_empty_hint_points_to_speaker_id() -> None:
    # U22: with no detected speakers (the default — live diarization is off), the modal explains
    # that naming happens after Speaker ID on the finished meeting, not "once the meeting has audio".
    from textual.widgets import Static

    sid = uuid4()
    existing = MeetingSession(id=sid, title="Meeting 2026-07-08")
    app, _container = _app_with_live_session(sid, existing, detected_speakers=frozenset())

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_name_speakers()
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, NameSpeakersScreen)
        texts = [str(w.render()) for w in screen.query(Static)]
        hint = next(t for t in texts if "No speakers detected" in t)
        assert "Speaker ID" in hint
        assert "Ctrl+D" in hint


async def test_name_speakers_action_no_session_notifies() -> None:
    # No current session → modal is not opened.
    sid = uuid4()
    existing = MeetingSession(id=sid, title="x")
    app, _container = _app_with_live_session(sid, existing)
    app.store = Store(state=initial_app_state())  # current_session_id is None

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_name_speakers()
        await pilot.pause()
        assert not isinstance(pilot.app.screen, NameSpeakersScreen)
