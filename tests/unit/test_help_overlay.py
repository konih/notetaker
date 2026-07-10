"""U16 — the ``?`` help/keymap overlay.

Acceptance:
- ``?`` opens a help view from the Live and Meetings screens.
- Help content stays in sync with the active keybindings (it is a pure projection
  of the real ``BINDINGS`` lists, so there is no second keymap to drift).
- The footer can stay concise without a discoverability regression: the overflow
  (hidden-from-footer) shortcuts still appear in the overlay.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import HelpScreen, TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import FOOTER_ACTIONS
from live_meeting_transcriber.ui.tui.help_overlay import (
    build_help_sections,
    format_help_markup,
    humanize_key,
)
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from textual.widgets import TabbedContent


def _make_app() -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.settings.ensure_data_dir.return_value = None
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


# --- pure key humanization ---------------------------------------------------


def test_humanize_key() -> None:
    assert humanize_key("ctrl+d") == "Ctrl+D"
    assert humanize_key("ctrl+1") == "Ctrl+1"
    assert humanize_key("q") == "Q"
    assert humanize_key("question_mark") == "?"
    # A binding that lists several keys renders them slash-joined.
    assert humanize_key("escape,q") == "Esc / Q"


# --- content is a projection of the live bindings ----------------------------


def test_sections_cover_global_and_meetings() -> None:
    sections = build_help_sections(TranscriberApp.BINDINGS, MeetingBrowser.BINDINGS)
    titles = [s.title for s in sections]
    assert titles == ["Global", "Meetings tab"]
    assert all(s.rows for s in sections), "each section must list at least one shortcut"


def test_global_section_lists_every_footer_action() -> None:
    # Sync guard: the overlay cannot silently omit a global binding — every
    # FOOTER_ACTIONS label (core *and* overflow) must appear as a row.
    sections = build_help_sections(TranscriberApp.BINDINGS, MeetingBrowser.BINDINGS)
    global_labels = {row.label for row in sections[0].rows}
    for action in FOOTER_ACTIONS:
        assert action.label in global_labels, f"{action.label} missing from help overlay"


def test_overflow_shortcuts_are_discoverable() -> None:
    # The whole point of the overlay after the U4 footer trim: hidden overflow
    # actions (e.g. Settings, Speaker ID) are still discoverable here.
    sections = build_help_sections(TranscriberApp.BINDINGS, MeetingBrowser.BINDINGS)
    markup = format_help_markup(sections)
    assert "Settings" in markup
    assert "Speaker ID" in markup
    assert "Delete meeting" in markup  # a Meetings-tab shortcut


# --- ? opens/closes the overlay from Live and Meetings -----------------------


async def test_question_mark_opens_help_from_live() -> None:
    app = _make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        depth = len(app.screen_stack)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert len(app.screen_stack) == depth + 1

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)
        assert len(app.screen_stack) == depth


async def test_question_mark_opens_help_from_meetings() -> None:
    app = _make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
