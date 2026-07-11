"""U11 — the Sessions modal is repurposed as a fuzzy "jump to meeting" picker.

Operator decision UX-OQ-1 (2026-07-10): keep the modal, but it stops being a second
browsing/management surface. The Meetings tab is the single home; the picker only finds a
meeting fast and jumps there. Management actions (rename/delete/refresh) leave the modal —
they live in the Meetings browser. `c: copy id` stays (U7): the picker is its only surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import SessionsScreen, TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import FOOTER_ACTIONS
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from textual.binding import Binding
from textual.widgets import DataTable, Input, TabbedContent

WEEKLY_ID = uuid4()
DESIGN_ID = uuid4()


def _sessions() -> list[MeetingSession]:
    return [
        MeetingSession(
            id=WEEKLY_ID,
            title="Weekly sync",
            started_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
        ),
        MeetingSession(
            id=DESIGN_ID,
            title="Design review",
            started_at=datetime(2026, 7, 10, 12, tzinfo=UTC),
        ),
    ]


def _container(tmp_path: Path) -> MagicMock:
    sessions = _sessions()
    c = MagicMock()
    c.sessions.list.side_effect = lambda: list(sessions)
    c.sessions.get.side_effect = lambda sid: next((s for s in sessions if s.id == sid), None)
    c.summaries.get_by_session.return_value = None
    c.transcripts.list_by_session.return_value = []
    c.session_speakers.get_map.return_value = {}
    c.settings.ensure_data_dir.return_value = tmp_path
    c.devices.list_sources.return_value = [object()]
    return c


def _app(container: MagicMock) -> TranscriberApp:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


# --- structure: the modal is a picker, not a second management surface -----


def test_picker_has_no_management_bindings() -> None:
    bindings = [b for b in SessionsScreen.BINDINGS if isinstance(b, Binding)]
    actions = {b.action for b in bindings}
    # Jump picker keeps close + copy-id only; rename/delete/refresh belong to the
    # Meetings home (single canonical surface, U11).
    assert "close" in actions
    assert "copy_id" in actions
    for gone in ("edit_title", "delete_selected", "refresh"):
        assert gone not in actions, f"management action {gone!r} must not live in the picker"


def test_footer_labels_the_j_key_as_jump() -> None:
    action = next(a for a in FOOTER_ACTIONS if a.action == "sessions")
    assert action.key == "j"
    assert "jump" in action.label.lower()


# --- behavior: find fast, jump to the single home ---------------------------


async def test_j_opens_the_jump_picker_with_filter_focused(tmp_path: Path) -> None:
    app = _app(_container(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        assert app.focused is app.screen.query_one("#sessions-filter", Input)


async def test_typing_fuzzy_filters_the_picker(tmp_path: Path) -> None:
    app = _app(_container(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionsScreen)
        table = screen.query_one("#sessions-table", DataTable)
        assert table.row_count == 2
        # Subsequence ("dsgn" ⊂ "Design review"), not just substring.
        screen.query_one("#sessions-filter", Input).value = "dsgn"
        for _ in range(3):
            await pilot.pause()
        assert table.row_count == 1


async def test_enter_jumps_to_the_meeting_in_the_single_home(tmp_path: Path) -> None:
    app = _app(_container(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionsScreen)
        screen.query_one("#sessions-filter", Input).value = "design"
        for _ in range(3):
            await pilot.pause()
        await pilot.press("enter")
        for _ in range(6):
            await pilot.pause()
        # Modal gone, Meetings tab active, the meeting selected in the browser.
        assert not isinstance(app.screen, SessionsScreen)
        assert app.query_one(TabbedContent).active == "tab-meetings"
        assert app.query_one(MeetingBrowser).selected_session_id == DESIGN_ID
