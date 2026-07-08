from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.config.device_prefs import (
    DevicePrefs,
    device_prefs_path,
    load_device_prefs,
    save_device_prefs,
)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_load_returns_empty_when_missing() -> None:
    prefs = load_device_prefs()
    assert prefs == DevicePrefs(monitor_source=None, microphone_source=None)


def test_save_then_load_round_trip() -> None:
    save_device_prefs(DevicePrefs(monitor_source=":4", microphone_source=":3"))
    assert device_prefs_path().is_file()
    loaded = load_device_prefs()
    assert loaded.monitor_source == ":4"
    assert loaded.microphone_source == ":3"


def test_load_tolerates_corrupt_file() -> None:
    path = device_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_device_prefs() == DevicePrefs()


def test_save_overwrites_previous() -> None:
    save_device_prefs(DevicePrefs(monitor_source=":1", microphone_source=":2"))
    save_device_prefs(DevicePrefs(monitor_source=":4", microphone_source=None))
    loaded = load_device_prefs()
    assert loaded.monitor_source == ":4"
    assert loaded.microphone_source is None
