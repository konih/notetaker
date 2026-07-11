"""U24 — meeting deletion is reachable and actually works.

The delete flow existed but was unreachable: its only keyboard trigger was a dead chord
(`ctrl+shift+d`/`shift+delete`/`ctrl+delete`, indistinguishable on standard terminals) and
it was buried in the `m` overflow menu — no visible button. This makes Delete a visible
primary toolbar button (red) and a working plain-`d` key, and proves the end-to-end path:
activate → confirm → `sessions.delete` → table refreshed → row gone.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_modals import ConfirmDeleteMeetingModal
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    overflow_toolbar_actions,
    primary_toolbar_actions,
    toolbar_action_by_button_id,
)
from textual.binding import Binding
from textual.widgets import Button, DataTable, TabbedContent

from tests.unit.conftest import make_mock_tui_container, make_tui_app


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
    container = make_mock_tui_container(tmp_path, [session])
    app = make_tui_app(container)

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

        # Observable outcome — the row is actually gone from the visible table, not just
        # from the mock's backing list (this is the user's complaint: "still there").
        assert table.row_count == 0

    container.sessions.delete.assert_called_once_with(sid)


async def test_delete_key_triggers_the_same_flow(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = make_mock_tui_container(tmp_path, [session])
    app = make_tui_app(container)

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


async def test_typing_d_in_a_meeting_field_does_not_delete(tmp_path: Path) -> None:
    # Safety: `d` is a plain, non-priority binding, so pressing it while editing a text field
    # (titles/notes are full of the letter d) must type — never trigger the delete confirm.
    from live_meeting_transcriber.ui.tui.tab_complete_input import TabCompletableInput

    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = make_mock_tui_container(tmp_path, [session])
    app = make_tui_app(container)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        browser.query_one("#meeting-sessions-table", DataTable).focus()
        await pilot.pause()
        title = browser.query_one("#meeting-title", TabCompletableInput)
        title.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmDeleteMeetingModal)
        assert "d" in title.value

    container.sessions.delete.assert_not_called()
