"""U14 — collapse the Meetings screen's three affordance layers into two channels.

Before U14 the Meetings tab announced the same actions on three concurrent
surfaces: the header hint line ("ctrl+s save · k summarize · ctrl+e edit line ·
m more actions"), the toolbar buttons (U9/U24), and the footer/help fallback
(U4/U16). U14 keeps exactly two channels — the toolbar as the one explicit
action surface, and the footer plus the ``?`` keymap overlay as the one
fallback — and strips the duplicated per-action key hints from the header. The
header keeps orientation only ("select a row") plus a pointer to ``?`` so the
fallback channel stays discoverable.

Acceptance:
- The Meetings screen no longer repeats the same actions across three
  concurrent affordance layers.
- Action discoverability remains acceptable through the retained channels.
- Layout is cleaner at 120-column and smaller terminals.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import FOOTER_ACTIONS
from live_meeting_transcriber.ui.tui.help_overlay import build_help_sections
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_toolbar import (
    overflow_toolbar_actions,
    primary_toolbar_actions,
)
from textual.binding import Binding
from textual.widgets import Static, TabbedContent

from tests.unit.conftest import make_mock_tui_container, make_tui_app


def _plain(markup: str) -> str:
    """Strip console markup tags so hints can be matched as plain text."""
    return re.sub(r"\[/?[^\[\]]*\]", "", markup)


async def _meetings_header_plain(app: TranscriberApp, pilot) -> str:  # type: ignore[no-untyped-def]
    app.query_one(TabbedContent).active = "tab-meetings"
    await pilot.pause()
    browser = app.query_one(MeetingBrowser)
    return _plain(str(browser.query_one("#meeting-browser-header", Static).render()))


# --- the header stops being a third action surface ----------------------------


async def test_header_no_longer_duplicates_action_hints(tmp_path: Path) -> None:
    """The header must not repeat actions already on the toolbar and footer/help.

    Before U14 it hinted save/summarize/edit-line/more-actions a third time; the
    toolbar (explicit surface) and footer + ``?`` overlay (fallback) already cover
    every one of them.
    """
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = make_tui_app(make_mock_tui_container(tmp_path, [session]))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        header = await _meetings_header_plain(app, pilot)
        low = header.lower()
        # No chorded key hint of any kind (ctrl+s save, ctrl+e edit line, …).
        assert "ctrl+" not in low, header
        # No per-action hint text duplicated from the toolbar/footer channels.
        for banned in ("save", "summarize", "edit line", "more actions"):
            assert banned not in low, header
        # Orientation text stays, and the fallback channel is pointed at.
        assert "select a row" in low, header
        assert "?" in header, header


async def test_header_is_single_line_even_at_80_cols(tmp_path: Path) -> None:
    """Cleanliness at 120-col and smaller: the trimmed header no longer wraps.

    The old ~88-char hint line wrapped to two rows at 80 columns, stacking a
    second line of clutter on top of the toolbar.
    """
    session = MeetingSession(id=uuid4(), title="Weekly sync")
    app = make_tui_app(make_mock_tui_container(tmp_path, [session]))
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        browser = app.query_one(MeetingBrowser)
        header = browser.query_one("#meeting-browser-header", Static)
        assert header.region.height == 1, f"header wraps: {header.region}"


# --- reduced clutter must not hide the critical actions ------------------------


def test_header_hinted_actions_remain_reachable() -> None:
    """Every action the old header duplicated stays discoverable in the two
    retained channels: as a toolbar button (or More… menu entry) and as a live
    keybinding surfaced by the footer/``?`` overlay."""
    primary_ids = {a.button_id for a in primary_toolbar_actions()}
    overflow_ids = {a.button_id for a in overflow_toolbar_actions()}
    assert {"meeting-btn-save", "meeting-btn-summarize"} <= primary_ids
    assert "meeting-btn-edit-line" in overflow_ids

    meetings_bound = {b.key: b.action for b in MeetingBrowser.BINDINGS if isinstance(b, Binding)}
    assert meetings_bound.get("ctrl+s") == "save_meeting"
    assert meetings_bound.get("ctrl+e") == "edit_segment"
    assert meetings_bound.get("m") == "show_more_menu"
    # Summarize stays on the canonical global key (UX-OQ-3 / U12).
    assert any(a.action == "summarize" and a.key == "k" for a in FOOTER_ACTIONS)


def test_help_overlay_still_lists_the_formerly_hinted_keys() -> None:
    # The ? overlay is the fallback channel of record: the keys the header used
    # to advertise must all be listed there (it projects live BINDINGS, U16).
    sections = build_help_sections(TranscriberApp.BINDINGS, MeetingBrowser.BINDINGS)
    meetings = next(s for s in sections if s.title == "Meetings tab")
    meeting_keys = {row.keys for row in meetings.rows}
    assert {"Ctrl+S", "Ctrl+E", "M"} <= meeting_keys
    global_keys = {row.keys for row in next(s for s in sections if s.title == "Global").rows}
    assert "K" in global_keys  # Summarize
