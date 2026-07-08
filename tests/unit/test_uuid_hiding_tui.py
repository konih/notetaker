"""U7 — raw UUIDs are hidden from primary meeting/session tables.

Acceptance: UUIDs are not shown in primary list headers/rows by default; users can
still retrieve the ID when needed; selection behaviour is unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import SessionsScreen, TranscriberApp
from textual.widgets import DataTable, TabbedContent


def _column_labels(table: DataTable) -> list[str]:
    return [str(col.label) for col in table.columns.values()]


def _all_cells(table: DataTable) -> list[str]:
    cells: list[str] = []
    for row_key in table.rows:
        cells.extend(str(c) for c in table.get_row(row_key))
    return cells


def _row_keys(table: DataTable) -> list[str]:
    return [rk.value for rk in table.rows if rk.value is not None]


def _make_app(container: MagicMock) -> TranscriberApp:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


def _mock_container(tmp_path, session: MeetingSession) -> MagicMock:
    container = MagicMock()
    container.sessions.list.return_value = [session]
    container.sessions.get.return_value = session
    container.summaries.get_by_session.return_value = None
    container.transcripts.list_by_session.return_value = []
    container.session_speakers.get_map.return_value = {}
    container.settings.ensure_data_dir.return_value = tmp_path
    return container


async def test_meetings_table_hides_uuid_but_keeps_selection_key(tmp_path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Weekly sync")
    container = _mock_container(tmp_path, session)

    app = _make_app(container)
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


async def test_sessions_modal_hides_uuid_column(tmp_path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Planning")
    container = _mock_container(tmp_path, session)
    app = _make_app(container)

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


async def test_sessions_modal_copy_id_copies_full_uuid(tmp_path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Planning")
    container = _mock_container(tmp_path, session)
    app = _make_app(container)

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
