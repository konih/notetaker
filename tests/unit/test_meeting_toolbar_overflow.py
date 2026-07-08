"""U9 — Meetings toolbar overflow.

The Meetings toolbar previously rendered ten buttons in one Horizontal row, which
wrapped to a second row (overflowed) at the 120-wide baseline. U9 reduces the
always-visible toolbar to a small set of primary actions plus a single "More…"
button that opens an overflow menu; every action stays reachable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingActionsMenu, MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    MEETING_TOOLBAR_ACTIONS,
    MORE_BUTTON_ID,
    overflow_toolbar_actions,
    primary_toolbar_actions,
    toolbar_action_by_button_id,
)
from textual.widgets import Button, TabbedContent

# --- pure partition -------------------------------------------------------


def test_primary_actions_are_a_small_set() -> None:
    primary = primary_toolbar_actions()
    assert 1 <= len(primary) <= 6
    # Fewer visible buttons than the original ten-button toolbar.
    assert len(primary) < len(MEETING_TOOLBAR_ACTIONS)


def test_primary_and_overflow_partition_all_actions() -> None:
    primary = primary_toolbar_actions()
    overflow = overflow_toolbar_actions()
    ids = [a.button_id for a in MEETING_TOOLBAR_ACTIONS]
    # No duplicate button ids and the two groups partition the whole catalog.
    assert len(ids) == len(set(ids))
    assert {a.button_id for a in primary}.isdisjoint({a.button_id for a in overflow})
    assert {a.button_id for a in primary} | {a.button_id for a in overflow} == set(ids)
    assert overflow, "there must be at least one overflow action"


def test_dynamic_state_buttons_stay_primary() -> None:
    # These two buttons are enabled/disabled dynamically by query_one(); keeping
    # them as always-present primary buttons avoids NoMatches when state changes.
    primary_ids = {a.button_id for a in primary_toolbar_actions()}
    assert "meeting-btn-continue-record" in primary_ids
    assert "meeting-btn-slide-preview" in primary_ids


def test_destructive_and_rare_actions_move_to_overflow() -> None:
    overflow_ids = {a.button_id for a in overflow_toolbar_actions()}
    assert "meeting-btn-delete" in overflow_ids  # destructive → hidden by default
    assert "meeting-btn-import-video" in overflow_ids
    assert "meeting-btn-refresh" in overflow_ids


def test_action_lookup_by_button_id() -> None:
    action = toolbar_action_by_button_id("meeting-btn-save")
    assert action is not None
    assert action.action == "action_save_meeting"
    assert toolbar_action_by_button_id("meeting-btn-does-not-exist") is None


def test_every_action_maps_to_a_real_browser_method() -> None:
    for a in MEETING_TOOLBAR_ACTIONS:
        assert callable(getattr(MeetingBrowser, a.action, None)), a.action


# --- real layout at 120x40 (Pilot) ---------------------------------------


def _make_app(container: MagicMock) -> TranscriberApp:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


def _mock_container(tmp_path: Path, session: MeetingSession) -> MagicMock:
    container = MagicMock()
    container.sessions.list.return_value = [session]
    container.sessions.get.return_value = session
    container.summaries.get_by_session.return_value = None
    container.transcripts.list_by_session.return_value = []
    container.session_speakers.get_map.return_value = {}
    container.settings.ensure_data_dir.return_value = tmp_path
    container.devices.list_sources.return_value = [object()]
    return container


async def _meetings_browser(app: TranscriberApp, pilot) -> MeetingBrowser:  # type: ignore[no-untyped-def]
    app.query_one(TabbedContent).active = "tab-meetings"
    await pilot.pause()
    return app.query_one(MeetingBrowser)


async def test_toolbar_fits_single_row_at_120w(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = _make_app(_mock_container(tmp_path, session))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await _meetings_browser(app, pilot)
        toolbar = app.query_one("#meeting-toolbar")
        # A single row of (bordered, height-3) buttons; wrapping doubles this.
        assert toolbar.size.height <= 3


async def test_more_button_present_and_overflow_buttons_absent(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = _make_app(_mock_container(tmp_path, session))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _meetings_browser(app, pilot)
        toolbar = browser.query_one("#meeting-toolbar")
        button_ids = {b.id for b in toolbar.query(Button)}
        assert MORE_BUTTON_ID in button_ids
        # Overflow actions are no longer standalone toolbar buttons.
        for a in overflow_toolbar_actions():
            assert a.button_id not in button_ids
        # Primary actions still render as buttons.
        for a in primary_toolbar_actions():
            assert a.button_id in button_ids


async def test_more_button_opens_overflow_menu(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = _make_app(_mock_container(tmp_path, session))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _meetings_browser(app, pilot)
        await browser.action_show_more_menu()
        await pilot.pause()
        assert isinstance(app.screen, MeetingActionsMenu)
        # The menu offers exactly the overflow actions, keyed by method name.
        option_ids = {app.screen.get_option_at_index(i).id for i in range(app.screen.option_count)}
        assert option_ids == {a.action for a in overflow_toolbar_actions()}


async def test_dispatch_toolbar_action_invokes_mapped_method(tmp_path: Path) -> None:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = _make_app(_mock_container(tmp_path, session))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _meetings_browser(app, pilot)
        spy = AsyncMock()
        browser.action_refresh_list = spy  # type: ignore[method-assign]
        await browser.dispatch_toolbar_action("action_refresh_list")
        spy.assert_awaited_once()
