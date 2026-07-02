"""Live tab inline editing of title/notes/attendees while a session is current."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from textual.widgets import Input, TextArea


def _make_app(container: MagicMock) -> tuple[TranscriberApp, Store]:
    store = Store()
    controller = MagicMock()
    app = TranscriberApp(store=store, container=container, controller=controller)
    return app, store


@pytest.mark.asyncio
async def test_live_tab_fields_disabled_with_no_current_session() -> None:
    container = MagicMock()
    app, _store = _make_app(container)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#live-title", Input).disabled is True
        assert app.query_one("#live-notes", TextArea).disabled is True
        assert app.query_one("#live-attendees", Input).disabled is True


@pytest.mark.asyncio
async def test_live_tab_fields_populate_when_session_becomes_current() -> None:
    sid = uuid4()
    container = MagicMock()
    container.sessions.get.return_value = MeetingSession(
        id=sid,
        title="Standup",
        notes="Existing notes",
        attendees=["Alice", "Bob"],
    )
    app, store = _make_app(container)

    async with app.run_test() as pilot:
        await pilot.pause()
        store.dispatch(
            act.RecordingStarted(
                session_id=sid,
                title="Standup",
                audio_source="sink.monitor",
                microphone_source=None,
                chunk_seconds=5,
                at=datetime(2026, 1, 1, 12, 0, 0),
            )
        )
        await pilot.pause()

        title_inp = app.query_one("#live-title", Input)
        notes_ta = app.query_one("#live-notes", TextArea)
        att_inp = app.query_one("#live-attendees", Input)

        assert title_inp.disabled is False
        assert title_inp.value == "Standup"
        assert notes_ta.disabled is False
        assert notes_ta.text == "Existing notes"
        assert att_inp.disabled is False
        assert att_inp.value == "Alice, Bob"


@pytest.mark.asyncio
async def test_live_tab_ctrl_s_saves_edited_fields_during_recording() -> None:
    sid = uuid4()
    container = MagicMock()
    container.sessions.get.return_value = MeetingSession(
        id=sid, title="Standup", notes="", attendees=[]
    )
    container.sessions.update_details.return_value = MeetingSession(
        id=sid,
        title="Standup (renamed)",
        notes="New context",
        attendees=["Alice", "Bob"],
    )
    app, store = _make_app(container)

    async with app.run_test() as pilot:
        await pilot.pause()
        store.dispatch(
            act.RecordingStarted(
                session_id=sid,
                title="Standup",
                audio_source="sink.monitor",
                microphone_source=None,
                chunk_seconds=5,
                at=datetime(2026, 1, 1, 12, 0, 0),
            )
        )
        await pilot.pause()

        app.query_one("#live-title", Input).value = "Standup (renamed)"
        app.query_one("#live-notes", TextArea).text = "New context"
        app.query_one("#live-attendees", Input).value = "Alice, Bob"

        await pilot.press("ctrl+s")
        await pilot.pause()

    container.sessions.update_details.assert_called_once_with(
        sid, title="Standup (renamed)", notes="New context", attendees=["Alice", "Bob"]
    )
    assert store.get_state().session_title == "Standup (renamed)"


@pytest.mark.asyncio
async def test_live_tab_save_without_current_session_is_a_noop() -> None:
    container = MagicMock()
    app, _store = _make_app(container)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

    container.sessions.update_details.assert_not_called()


@pytest.mark.asyncio
async def test_typing_priority_letters_into_live_title_does_not_trigger_global_actions() -> None:
    """'w' (export) and 'k' (summarize) are priority bindings — they must not eat keystrokes
    typed into an editable Live tab field instead of inserting the character."""
    sid = uuid4()
    container = MagicMock()
    container.sessions.get.return_value = MeetingSession(id=sid, title="Standup")
    app, store = _make_app(container)

    async with app.run_test() as pilot:
        await pilot.pause()
        store.dispatch(
            act.RecordingStarted(
                session_id=sid,
                title="Standup",
                audio_source="sink.monitor",
                microphone_source=None,
                chunk_seconds=5,
                at=datetime(2026, 1, 1, 12, 0, 0),
            )
        )
        await pilot.pause()

        title_inp = app.query_one("#live-title", Input)
        title_inp.value = ""
        title_inp.focus()
        await pilot.pause()
        await pilot.press("w", "k")
        await pilot.pause()

        assert title_inp.value == "wk"

    container.sessions.update_details.assert_not_called()
