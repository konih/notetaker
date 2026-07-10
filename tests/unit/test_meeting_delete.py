"""U24 — meeting deletion is reachable and actually works.

The delete flow existed but was unreachable: its only keyboard trigger was a dead chord
(`ctrl+shift+d`/`shift+delete`/`ctrl+delete`, indistinguishable on standard terminals) and
it was buried in the `m` overflow menu — no visible button. This makes Delete a visible
primary toolbar button (red) and a working plain-`d` key, and proves the end-to-end path:
activate → confirm → `sessions.delete` → table refreshed → row gone.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import ConfirmDeleteMeetingModal, MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    overflow_toolbar_actions,
    primary_toolbar_actions,
    toolbar_action_by_button_id,
)
from textual.binding import Binding
from textual.widgets import Button, DataTable, TabbedContent


def _container(tmp_path: Path, sessions: list[MeetingSession]) -> MagicMock:
    store_list = list(sessions)
    c = MagicMock()
    c.sessions.list.side_effect = lambda: list(store_list)

    def _get(sid: object) -> MeetingSession | None:
        return next((s for s in store_list if s.id == sid), None)

    def _delete(sid: object) -> bool:
        before = len(store_list)
        store_list[:] = [s for s in store_list if s.id != sid]
        return len(store_list) < before

    c.sessions.get.side_effect = _get
    c.sessions.delete.side_effect = _delete
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


async def _browser(app: TranscriberApp, pilot) -> MeetingBrowser:  # type: ignore[no-untyped-def]
    app.query_one(TabbedContent).active = "tab-meetings"
    await pilot.pause()
    return app.query_one(MeetingBrowser)


# --- structure: Delete is a visible primary button, not overflow/dead-chord ---


def test_delete_is_a_visible_primary_error_button() -> None:
    primary_ids = {a.button_id for a in primary_toolbar_actions()}
    overflow_ids = {a.button_id for a in overflow_toolbar_actions()}
    assert "meeting-btn-delete" in primary_ids
    assert "meeting-btn-delete" not in overflow_ids
    action = toolbar_action_by_button_id("meeting-btn-delete")
    assert action is not None
    assert action.variant == "error"  # rendered red — destructive


def test_delete_binding_is_a_working_key_not_a_dead_chord() -> None:
    # The dead ctrl+shift+d / shift+delete / ctrl+delete chord is replaced by plain `d`
    # (focus stays on the meetings table after selecting a row, so `d` fires there).
    bindings = [b for b in MeetingBrowser.BINDINGS if isinstance(b, Binding)]
    delete = next(b for b in bindings if b.action == "delete_meeting")
    assert delete.key == "d"
    assert "shift" not in delete.key and "ctrl" not in delete.key


# --- behavior: the reported bug — deletion actually removes the meeting ---


async def test_delete_button_removes_the_meeting_end_to_end(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = _container(tmp_path, [session])
    app = _app(container)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        table.focus()
        await pilot.pause()
        assert browser.selected_session_id == sid

        # Activate the visible Delete button.
        delete_btn = browser.query_one("#meeting-btn-delete", Button)
        delete_btn.press()
        await pilot.pause()

        # Confirm the modal.
        assert isinstance(app.screen, ConfirmDeleteMeetingModal)
        await pilot.press("y")
        for _ in range(6):
            await pilot.pause()

    container.sessions.delete.assert_called_once_with(sid)
    assert container.sessions.list() == []  # row actually gone


async def test_delete_key_triggers_the_same_flow(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = _container(tmp_path, [session])
    app = _app(container)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        browser.query_one("#meeting-sessions-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDeleteMeetingModal)
        await pilot.press("y")
        for _ in range(6):
            await pilot.pause()

    container.sessions.delete.assert_called_once_with(sid)
