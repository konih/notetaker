"""Redesign — the Meetings detail pane's Overview/Transcript/Summary sub-tabs.

Guards the Tabs → ContentSwitcher wiring: every sub-tab must reach its pane,
and the editing widgets keep their ids (all save/summarize actions query them).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from textual.widgets import ContentSwitcher, TabbedContent, Tabs

from tests.unit.conftest import make_mock_tui_container, make_tui_app


def _make_app(tmp_path: Path) -> TranscriberApp:
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    return make_tui_app(make_mock_tui_container(tmp_path, [session]))


async def test_detail_sub_tabs_switch_panes(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        browser = app.query_one(MeetingBrowser)
        switcher = browser.query_one("#detail-switcher", ContentSwitcher)
        tabs = browser.query_one("#detail-tabs", Tabs)

        assert switcher.current == "detail-overview"
        for tab_id, pane_id in (
            ("dt-transcript", "detail-transcript"),
            ("dt-summary", "detail-summary"),
            ("dt-overview", "detail-overview"),
        ):
            tabs.active = tab_id
            await pilot.pause()
            assert switcher.current == pane_id


async def test_detail_edit_widgets_keep_their_ids(tmp_path: Path) -> None:
    # The save/summarize/edit actions all query these ids; the sub-tab
    # restructure must not orphan any of them.
    app = _make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        browser = app.query_one(MeetingBrowser)
        for wid in (
            "#meeting-title",
            "#meeting-notes",
            "#meeting-attendees",
            "#meeting-summary",
            "#meeting-transcript",
            "#meeting-speaker-area",
        ):
            assert browser.query_one(wid) is not None
