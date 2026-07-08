"""U19 — the in-app header shows meeting context, not a duplicated app title."""

from __future__ import annotations

from unittest.mock import MagicMock

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from textual.widgets._header import HeaderTitle


def _app(**state_updates: object) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    store = Store(state=initial_app_state().model_copy(update=state_updates))
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


async def test_header_shows_context_without_app_name() -> None:
    app = _app(session_title="Team sync")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        header = str(app.query_one(HeaderTitle).render())

        # Meeting context stays visible.
        assert "Team sync" in header
        # The static app name is no longer duplicated inside the header.
        assert "live-meeting-transcriber" not in header
        # App identity is still available (terminal title / command palette).
        assert app.title == "live-meeting-transcriber"


async def test_header_updates_on_session_title_change() -> None:
    app = _app(session_title="No session")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.sub_title = "⏺ Standup"
        await pilot.pause()
        header = str(app.query_one(HeaderTitle).render())
        assert "Standup" in header
        assert "live-meeting-transcriber" not in header
