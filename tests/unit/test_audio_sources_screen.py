"""Pilot tests for the AudioSourcesScreen picker.

Regression guard: textual renamed the Select blank sentinel from ``Select.BLANK`` to
``Select.NULL``. On textual 8.x ``Select.BLANK`` silently resolves to an unrelated
``Widget.BLANK == False``, which ``Select`` rejects with ``InvalidSelectValueError`` at
mount time — crashing the whole TUI whenever the picker was opened with no matching
saved source. Mounting the screen here catches that.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from live_meeting_transcriber.ui.tui.app import (
    AudioSourcesScreen,
    TranscriberApp,
)
from textual.widgets import Select

from tests.unit.conftest import make_tui_app


@dataclass(frozen=True)
class _Source:
    name: str
    description: str


def _app(
    *, sources: list[_Source], state_updates: dict[str, object] | None = None
) -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    container.devices.list_sources.return_value = list(sources)
    return make_tui_app(container, state_updates=state_updates)


async def test_screen_mounts_with_no_saved_source() -> None:
    # The default state has audio_source=None (no saved selection), which drives both
    # Selects onto the blank sentinel — the exact path that used to crash on mount.
    app = _app(sources=[_Source("mon.1", "Monitor 1"), _Source("mic.1", "Mic 1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(AudioSourcesScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AudioSourcesScreen)
        assert screen.query_one("#monitor-select", Select).value is Select.NULL


async def test_screen_mounts_with_saved_source_selected() -> None:
    app = _app(
        sources=[_Source("mon.1", "Monitor 1"), _Source("mic.1", "Mic 1")],
        state_updates={"audio_source": "mon.1", "configured_microphone_source": "mic.1"},
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(AudioSourcesScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AudioSourcesScreen)
        assert screen.query_one("#monitor-select", Select).value == "mon.1"
        assert screen.query_one("#mic-select", Select).value == "mic.1"


async def test_save_with_blank_monitor_persists_none() -> None:
    app = _app(sources=[_Source("mon.1", "Monitor 1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(AudioSourcesScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AudioSourcesScreen)
        await screen.action_save()
        await pilot.pause()
    # blank monitor selection saves as "no source" rather than the literal sentinel
    assert app.store.get_state().audio_source is None
