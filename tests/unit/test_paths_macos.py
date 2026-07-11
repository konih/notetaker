"""F5: macOS-native default locations (`~/Library/Application Support`) with legacy fallback.

Contract (FEAT-05, operator decision OQ-2 "macOS is first-class"):

- On macOS, *fresh* installs default config and data to
  ``~/Library/Application Support/live-meeting-transcriber``.
- Existing installs are never stranded: if the legacy XDG directory
  (``~/.config/...`` for config, ``~/.local/share/...`` for data) already exists,
  it keeps winning.
- ``XDG_CONFIG_HOME`` set in the environment always wins (explicit user intent;
  also how the test suite isolates itself).
- Non-darwin behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.config import paths


@pytest.fixture()
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    return home


def _set_platform(monkeypatch: pytest.MonkeyPatch, darwin: bool) -> None:
    monkeypatch.setattr(paths, "_is_darwin", lambda: darwin)


MAC_DIR_PARTS = ("Library", "Application Support", "live-meeting-transcriber")


class TestConfigDir:
    def test_darwin_fresh_install_uses_library(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert paths.app_config_dir() == fake_home.joinpath(*MAC_DIR_PARTS).resolve()

    def test_darwin_legacy_xdg_dir_keeps_winning(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        legacy = fake_home / ".config" / "live-meeting-transcriber"
        legacy.mkdir(parents=True)
        assert paths.app_config_dir() == legacy.resolve()

    def test_darwin_explicit_xdg_config_home_env_wins(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path, tmp_path: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        custom = tmp_path / "custom-xdg"
        custom.mkdir()
        monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
        assert paths.app_config_dir() == (custom / "live-meeting-transcriber").resolve()

    def test_non_darwin_unchanged(self, monkeypatch: pytest.MonkeyPatch, fake_home: Path) -> None:
        _set_platform(monkeypatch, darwin=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert paths.app_config_dir() == (fake_home / ".config" / "live-meeting-transcriber").resolve()


class TestDataDir:
    def test_darwin_fresh_install_uses_library(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        assert paths.default_data_dir() == fake_home.joinpath(*MAC_DIR_PARTS).resolve()

    def test_darwin_legacy_xdg_dir_keeps_winning(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        legacy = fake_home / ".local" / "share" / "live-meeting-transcriber"
        legacy.mkdir(parents=True)
        assert paths.default_data_dir() == legacy.resolve()

    def test_non_darwin_unchanged(self, monkeypatch: pytest.MonkeyPatch, fake_home: Path) -> None:
        _set_platform(monkeypatch, darwin=False)
        assert (
            paths.default_data_dir()
            == (fake_home / ".local" / "share" / "live-meeting-transcriber").resolve()
        )

    def test_default_database_url_follows_data_dir(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        _set_platform(monkeypatch, darwin=True)
        expected = fake_home.joinpath(*MAC_DIR_PARTS).resolve() / "app.db"
        assert paths.default_database_url() == f"sqlite:////{expected}"


def test_is_darwin_reflects_sys_platform() -> None:
    import sys

    assert paths._is_darwin() == (sys.platform == "darwin")
