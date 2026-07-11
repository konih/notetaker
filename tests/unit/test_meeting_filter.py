"""U17 — search/filter in the browse home (Meetings tab).

The Meetings browser is the single canonical browsing surface (U11), so the filter lives
there: a `/`-focusable input above the meetings table that narrows rows by free text
(F2 metadata semantics) and `after:`/`before:` date tokens, with an explicit empty-result
state and selection/detail kept in sync.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from textual.widgets import DataTable, Input, Static, TabbedContent

from tests.unit.conftest import make_mock_tui_container, make_tui_app

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


async def _browser(app: TranscriberApp, pilot) -> MeetingBrowser:  # type: ignore[no-untyped-def]
    app.query_one(TabbedContent).active = "tab-meetings"
    await pilot.pause()
    return app.query_one(MeetingBrowser)


async def _set_filter(browser: MeetingBrowser, pilot, value: str) -> None:  # type: ignore[no-untyped-def]
    inp = browser.query_one("#meeting-filter", Input)
    inp.value = value
    for _ in range(3):
        await pilot.pause()


async def test_filter_input_exists_above_the_meetings_table(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        assert browser.query_one("#meeting-filter", Input) is not None


async def test_typing_narrows_the_table_by_title(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        assert table.row_count == 2
        await _set_filter(browser, pilot, "design")
        assert table.row_count == 1


async def test_date_token_filters_by_started_date(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        await _set_filter(browser, pilot, "after:2026-07-05")
        assert table.row_count == 1


async def test_slash_focuses_the_filter_from_the_table(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        browser.query_one("#meeting-sessions-table", DataTable).focus()
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        assert app.focused is browser.query_one("#meeting-filter", Input)


async def test_empty_result_state_is_explicit_and_actionable(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        await _set_filter(browser, pilot, "zzz-no-such-meeting")
        assert table.row_count == 0
        status = str(browser.query_one("#meeting-detail-status", Static).render()).lower()
        # Explicit: says nothing matched; actionable: says how to clear.
        assert "match" in status
        assert "esc" in status or "clear" in status


async def test_escape_clears_the_filter_and_returns_focus_to_the_table(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        inp = browser.query_one("#meeting-filter", Input)
        await _set_filter(browser, pilot, "zzz-no-such-meeting")
        inp.focus()
        await pilot.pause()
        await pilot.press("escape")
        for _ in range(3):
            await pilot.pause()
        assert inp.value == ""
        assert table.row_count == 2
        assert app.focused is table


async def test_selection_and_detail_stay_in_sync_when_filtered_out(tmp_path: Path) -> None:
    app = make_tui_app(make_mock_tui_container(tmp_path, _sessions()))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        browser = await _browser(app, pilot)
        table = browser.query_one("#meeting-sessions-table", DataTable)
        table.focus()
        await pilot.pause()
        assert browser.selected_session_id == WEEKLY_ID
        # Filtering the selected meeting out must not leave the detail pane showing it.
        await _set_filter(browser, pilot, "design")
        assert browser.selected_session_id != WEEKLY_ID
