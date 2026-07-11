"""U19 — the top-of-app chrome shows meeting context, not a duplicated app title.

Originally asserted against the stock Textual ``Header``; the redesign replaced
it with the :class:`StatusDeck`, which keeps the same contract: meeting context
visible, app name not repeated inside the app, app identity retained for the
terminal title / command palette.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.utils.time import utc_now
from textual.widgets import Static

from tests.unit.conftest import make_tui_app


def _app(**state_updates: object) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    return make_tui_app(container, state_updates=state_updates)


async def test_deck_shows_context_without_app_name() -> None:
    app = _app(session_title="Team sync")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        deck = str(app.query_one("#deck-main", Static).render())

        # Meeting context stays visible.
        assert "Team sync" in deck
        # The static app name is no longer duplicated inside the app (U19).
        assert "live-meeting-transcriber" not in deck
        # App identity is still available (terminal title / command palette).
        assert app.title == "live-meeting-transcriber"


async def test_deck_updates_on_session_title_change() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.store.dispatch(
            act.RecordingStartRequested(title="Standup", audio_source=None, at=utc_now())
        )
        await pilot.pause()
        deck = str(app.query_one("#deck-main", Static).render())
        assert "Standup" in deck
        assert "live-meeting-transcriber" not in deck
