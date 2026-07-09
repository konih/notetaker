"""U21 — Pilot tests for the folder/file picker and the editable Settings screen."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml
from live_meeting_transcriber.config.settings import (
    Settings,
    default_config_yaml_path,
)
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import (
    EditSettingsScreen,
    PathPickerScreen,
    SettingsScreen,
    TranscriberApp,
)
from textual.widgets import Input, Static


def _app() -> TranscriberApp:
    container = MagicMock()
    container.sessions.list.return_value = []
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return TranscriberApp(store=store, container=container, controller=controller)


async def test_picker_select_existing_dir_dismisses_with_resolved_path(tmp_path: Path) -> None:
    app = _app()
    result: dict[str, object] = {}
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(
            PathPickerScreen(kind="dir", start=None, title="Pick folder"),
            callback=lambda r: result.__setitem__("v", r),
        )
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, PathPickerScreen)
        screen.query_one("#picker-path", Input).value = str(tmp_path)
        await screen.action_select()
        await pilot.pause()
    assert result["v"] == tmp_path.resolve()


async def test_picker_blocks_nonexistent(tmp_path: Path) -> None:
    app = _app()
    result: dict[str, object] = {}
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(
            PathPickerScreen(kind="dir", start=None, title="Pick folder"),
            callback=lambda r: result.__setitem__("v", r),
        )
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, PathPickerScreen)
        screen.query_one("#picker-path", Input).value = str(tmp_path / "missing")
        await screen.action_select()
        await pilot.pause()
        # still open, nothing dismissed
        assert isinstance(pilot.app.screen, PathPickerScreen)
    assert "v" not in result


async def test_edit_settings_save_persists_to_yaml(tmp_path: Path) -> None:
    people = tmp_path / "People"
    people.mkdir()
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        # simulate a picker returning a folder for obsidian_people_dir
        screen.set_pending("obsidian_people_dir", people.resolve())
        await screen.action_save()
        await pilot.pause()

    raw = yaml.safe_load(default_config_yaml_path().read_text(encoding="utf-8"))
    assert raw["obsidian_people_dir"] == str(people.resolve())


async def test_edit_settings_clear_writes_null(tmp_path: Path) -> None:
    # Seed a config.yaml with a value, then clear it in-app.
    people = tmp_path / "People"
    people.mkdir()
    cfg = default_config_yaml_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"obsidian_people_dir: {people.resolve()}\n", encoding="utf-8")

    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        assert screen.query_one("#val-obsidian_people_dir", Static)  # row exists
        screen.set_pending("obsidian_people_dir", None)
        await screen.action_save()
        await pilot.pause()

    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert raw["obsidian_people_dir"] is None


async def test_settings_screen_opens_editor() -> None:
    app = _app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(SettingsScreen())
        await pilot.pause()
        assert isinstance(pilot.app.screen, SettingsScreen)
        pilot.app.screen.action_edit()
        await pilot.pause()
        assert isinstance(pilot.app.screen, EditSettingsScreen)
