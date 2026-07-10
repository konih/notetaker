"""U4 — the global footer shows only core actions; the rest stay reachable.

Acceptance:
- Footer text fits standard terminal widths without truncation.
- Core actions remain one-keystroke accessible.
- Non-core actions are still discoverable through the command palette and remain
  bound to a key.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import (
    FOOTER_ACTIONS,
    core_footer_actions,
    overflow_footer_actions,
)
from textual.app import SystemCommand
from textual.binding import Binding
from textual.widgets import Footer, TabbedContent
from textual.widgets._footer import FooterKey

# Standard-terminal target width the footer must fit within (stricter than the
# 120-col checks earlier stories used).
STANDARD_WIDTH = 80


def _make_app() -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.settings.ensure_data_dir.return_value = None
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


# --- pure catalog invariants -------------------------------------------------


def test_catalog_is_wellformed() -> None:
    keys = [a.key for a in FOOTER_ACTIONS]
    actions = [a.action for a in FOOTER_ACTIONS]
    assert len(keys) == len(set(keys)), "duplicate footer keys"
    assert len(actions) == len(set(actions)), "duplicate footer actions"
    # Core + overflow partition the whole catalog.
    assert set(core_footer_actions()) | set(overflow_footer_actions()) == set(FOOTER_ACTIONS)
    assert set(core_footer_actions()) & set(overflow_footer_actions()) == set()
    # Core stays small (that is the point of the story) but non-empty.
    assert 0 < len(core_footer_actions()) <= 6


def test_every_catalog_action_has_an_app_method() -> None:
    # Guards against typos in the catalog: every action must map to a handler.
    for entry in FOOTER_ACTIONS:
        assert hasattr(TranscriberApp, f"action_{entry.action}"), entry.action


# --- reachability: core one-key, overflow still bound ------------------------


def test_all_actions_remain_key_bound() -> None:
    bindings = [b for b in TranscriberApp.BINDINGS if isinstance(b, Binding)]
    by_key = {b.key: b for b in bindings}
    for entry in FOOTER_ACTIONS:
        binding = by_key.get(entry.key)
        assert binding is not None, f"{entry.key} not bound"
        assert binding.action == entry.action
        # Core shows in the footer; overflow is hidden but still bound.
        assert binding.show is entry.core
        assert bool(binding.priority) is bool(entry.priority)


# --- render: footer fits the standard width without truncation --------------


async def test_footer_fits_standard_width_and_shows_only_core() -> None:
    app = _make_app()
    async with app.run_test(size=(STANDARD_WIDTH, 24)) as pilot:
        await pilot.pause()
        footer_keys = list(app.query(FooterKey))
        shown = {k.description for k in footer_keys}

        core_labels = {a.label for a in core_footer_actions()}
        overflow_labels = {a.label for a in overflow_footer_actions()}

        # Every core action is visible in the footer...
        assert core_labels <= shown
        # ...and no overflow action leaks into the footer.
        assert shown.isdisjoint(overflow_labels)

        # Real render check: the laid-out footer content fits the width, so no key
        # is clipped or truncated (Textual clips overflow rather than wrapping).
        total = sum(k.size.width for k in footer_keys)
        assert total <= STANDARD_WIDTH, f"footer content {total} > {STANDARD_WIDTH}"
        # Footer is a single row.
        assert app.query_one(Footer).size.height == 1

        # AC1 says "common screens" — the Meetings tab must also fit (the focused
        # browser adds no extra footer bindings, but assert it rather than assume).
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        meetings_total = sum(k.size.width for k in app.query(FooterKey))
        assert meetings_total <= STANDARD_WIDTH, (
            f"meetings footer {meetings_total} > {STANDARD_WIDTH}"
        )


# --- discoverability: overflow actions live in the command palette ----------


async def test_overflow_actions_are_in_the_command_palette() -> None:
    app = _make_app()
    async with app.run_test(size=(STANDARD_WIDTH, 24)) as pilot:
        await pilot.pause()
        commands = list(app.get_system_commands(app.screen))
        titles = {c.title for c in commands}
        for entry in overflow_footer_actions():
            assert entry.label in titles, f"{entry.label} missing from palette"
        # Every yielded item is a real SystemCommand with an invocable callback.
        for c in commands:
            assert isinstance(c, SystemCommand)
            assert callable(c.callback)

        # Invoking a palette callback must actually run its action — not silently
        # no-op. "Settings" pushes the settings modal (the palette awaits the
        # coroutine the callback returns, exactly as Textual's palette does).
        settings_cmd = next(c for c in commands if c.title == "Settings")
        depth_before = len(app.screen_stack)
        result = settings_cmd.callback()
        if result is not None:
            await result
        await pilot.pause()
        assert len(app.screen_stack) == depth_before + 1
        assert type(app.screen).__name__ == "SettingsScreen"
