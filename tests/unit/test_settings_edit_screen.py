"""U21/U15 — Pilot tests for the picker and the editable Settings screen (paths + scalars)."""

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
from live_meeting_transcriber.ui.tui.settings_view import build_settings_sections
from textual.widgets import Input, Static, Switch


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


async def test_browse_button_through_picker_persists(tmp_path: Path) -> None:
    # End-to-end glue: Browse button -> picker -> _apply callback -> set_pending -> Save.
    # If any link is broken the folder picker is dead on arrival, so exercise the full chain.
    people = tmp_path / "People"
    people.mkdir()
    app = _app()
    async with app.run_test(size=(120, 48)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        edit_screen = pilot.app.screen
        assert isinstance(edit_screen, EditSettingsScreen)

        await pilot.click("#browse-obsidian_people_dir")
        await pilot.pause()
        picker = pilot.app.screen
        assert isinstance(picker, PathPickerScreen)
        picker.query_one("#picker-path", Input).value = str(people.resolve())
        await picker.action_select()
        await pilot.pause()

        # back on the edit screen, the picker result reached set_pending via _apply
        assert isinstance(pilot.app.screen, EditSettingsScreen)
        assert edit_screen.query_one("#val-obsidian_people_dir", Static)  # row exists
        assert edit_screen._pending["obsidian_people_dir"] == people.resolve()
        await edit_screen.action_save()
        await pilot.pause()

    raw = yaml.safe_load(default_config_yaml_path().read_text(encoding="utf-8"))
    assert raw["obsidian_people_dir"] == str(people.resolve())


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


# --- U15: safe runtime scalar toggles -----------------------------------------------------


async def test_edit_settings_scalar_widgets_show_current_values() -> None:
    cfg = default_config_yaml_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("keep_audio_chunks: true\naudio_chunk_seconds: 25\n", encoding="utf-8")

    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        assert screen.query_one("#switch-keep_audio_chunks", Switch).value is True
        assert screen.query_one("#switch-audio_silence_skip_enabled", Switch).value is True
        assert screen.query_one("#input-audio_chunk_seconds", Input).value == "25"


async def test_edit_settings_scalar_save_persists_to_yaml() -> None:
    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        screen.query_one("#switch-keep_audio_chunks", Switch).value = True
        screen.query_one("#input-audio_silence_threshold_dbfs", Input).value = "-55"
        await screen.action_save()
        await pilot.pause()

    raw = yaml.safe_load(default_config_yaml_path().read_text(encoding="utf-8"))
    assert raw["keep_audio_chunks"] is True
    assert raw["audio_silence_threshold_dbfs"] == -55.0


async def test_edit_settings_out_of_range_scalar_blocks_save() -> None:
    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        screen.query_one("#input-audio_silence_threshold_dbfs", Input).value = "-200"
        await screen.action_save()
        await pilot.pause()
        # still open, inline error shown, nothing written
        assert isinstance(pilot.app.screen, EditSettingsScreen)
        err = screen.query_one("#err-audio_silence_threshold_dbfs", Static)
        assert str(err.content).strip()
    assert not default_config_yaml_path().exists()


async def test_edit_settings_unparseable_scalar_blocks_save() -> None:
    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        screen.query_one("#input-audio_chunk_seconds", Input).value = "ten"
        await screen.action_save()
        await pilot.pause()
        assert isinstance(pilot.app.screen, EditSettingsScreen)
        err = screen.query_one("#err-audio_chunk_seconds", Static)
        assert str(err.content).strip()
    assert not default_config_yaml_path().exists()


async def test_edit_settings_save_error_then_fix_saves() -> None:
    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        field_input = screen.query_one("#input-audio_chunk_seconds", Input)
        field_input.value = "0"
        await screen.action_save()
        await pilot.pause()
        assert isinstance(pilot.app.screen, EditSettingsScreen)
        field_input.value = "30"
        await screen.action_save()
        await pilot.pause()
        # inline error cleared on the successful save
        assert not str(screen.query_one("#err-audio_chunk_seconds", Static).content).strip()

    raw = yaml.safe_load(default_config_yaml_path().read_text(encoding="utf-8"))
    assert raw["audio_chunk_seconds"] == 30


async def test_edit_settings_scalar_save_refreshes_read_only_view() -> None:
    app = _app()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        assert app.store.get_state().finalize_on_session_stop is False
        app.push_screen(EditSettingsScreen())
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, EditSettingsScreen)
        screen.query_one("#switch-finalize_on_session_stop", Switch).value = True
        await screen.action_save()
        await pilot.pause()

        state = app.store.get_state()
        assert state.finalize_on_session_stop is True
        sections = dict(build_settings_sections(state))
        assert "Label speakers after the meeting: on" in sections["Speaker labels"]
