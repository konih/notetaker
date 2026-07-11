"""U7 — raw UUIDs are hidden from primary meeting/session tables.

Acceptance: UUIDs are not shown in primary list headers/rows by default; users can
still retrieve the ID when needed; selection behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import SessionsScreen
from textual.widgets import DataTable, Static, TabbedContent

from tests.unit.conftest import make_mock_tui_container, make_tui_app


def _column_labels(table: DataTable[Any]) -> list[str]:
    return [str(col.label) for col in table.columns.values()]


def _all_cells(table: DataTable[Any]) -> list[str]:
    cells: list[str] = []
    for row_key in table.rows:
        cells.extend(str(c) for c in table.get_row(row_key))
    return cells


def _row_keys(table: DataTable[Any]) -> list[str]:
    return [rk.value for rk in table.rows if rk.value is not None]


async def test_meetings_table_hides_uuid_but_keeps_selection_key(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = make_mock_tui_container(tmp_path, [session])

    app = make_tui_app(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        table = app.query_one("#meeting-sessions-table", DataTable)

        # No UUID column header in the primary meetings table.
        assert "Session" not in _column_labels(table)
        # No UUID (full or truncated) rendered in any cell.
        assert not any(str(sid)[:8] in cell for cell in _all_cells(table))
        # Selection still keyed by the full UUID (retrievable programmatically).
        assert str(sid) in _row_keys(table)
        # Retrieval path preserved: the selected-session detail line shows the full UUID.
        detail = str(app.query_one("#meeting-detail-status", Static).render())
        assert str(sid) in detail


async def test_sessions_modal_hides_uuid_column(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Planning")
    container = make_mock_tui_container(tmp_path, [session])
    app = make_tui_app(container)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = SessionsScreen()
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#sessions-table", DataTable)

        assert "Id" not in _column_labels(table)
        assert not any(str(sid)[:8] in cell for cell in _all_cells(table))
        # Selection key still carries the full UUID.
        assert str(sid) in _row_keys(table)


async def test_sessions_modal_copy_id_copies_full_uuid(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Planning")
    container = make_mock_tui_container(tmp_path, [session])
    app = make_tui_app(container)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = SessionsScreen()
        app.push_screen(screen)
        await pilot.pause()
        table = screen.query_one("#sessions-table", DataTable)
        table.move_cursor(row=0)
        await pilot.pause()

        copied: list[str] = []
        app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign]
        await screen.action_copy_id()
        await pilot.pause()

        # The full UUID is retrievable via the copy action.
        assert copied == [str(sid)]
