"""Filesystem locations for config and data (XDG-aware, macOS-native), shared by all settings areas.

Split out of ``config/settings.py`` (A8) so per-area section models can use the
path helpers without importing the aggregate ``Settings`` model.

macOS (F5): fresh installs default both config and data to
``~/Library/Application Support/live-meeting-transcriber`` (Apple convention).
Existing installs are never stranded — if the legacy XDG directory already
exists it keeps winning, and an explicit ``$XDG_CONFIG_HOME`` always wins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_CONFIG_DIR_NAME = "live-meeting-transcriber"
APP_DATA_DIR_NAME = "live-meeting-transcriber"

APP_CONFIG_YAML_NAME = "config.yaml"


def _is_darwin() -> bool:
    """Platform seam (monkeypatched in tests)."""
    return sys.platform == "darwin"


def _macos_app_support_dir() -> Path:
    return (Path.home() / "Library" / "Application Support" / APP_DATA_DIR_NAME).resolve()


def default_data_dir() -> Path:
    """Default directory for app data (SQLite DB, logs, chunk audio).

    Linux: ``~/.local/share/live-meeting-transcriber`` (XDG). macOS: same path if it
    already exists (legacy installs keep their data in place), otherwise
    ``~/Library/Application Support/live-meeting-transcriber``.
    """
    legacy = (Path.home() / ".local" / "share" / APP_DATA_DIR_NAME).resolve()
    if _is_darwin() and not legacy.is_dir():
        return _macos_app_support_dir()
    return legacy


def default_database_url() -> str:
    return f"sqlite:////{default_data_dir() / 'app.db'}"


def xdg_config_home() -> Path:
    """XDG base directory for user-specific configuration (``$XDG_CONFIG_HOME`` or ``~/.config``)."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config").resolve()


def app_config_dir() -> Path:
    """Directory holding ``config.yaml``, ``.env``, and device prefs.

    ``$XDG_CONFIG_HOME`` always wins when set (explicit user intent; test isolation).
    Otherwise ``~/.config/live-meeting-transcriber`` — except on macOS, where fresh
    installs (no legacy dir yet) use ``~/Library/Application Support``.
    """
    if os.environ.get("XDG_CONFIG_HOME"):
        return xdg_config_home() / APP_CONFIG_DIR_NAME
    legacy = (Path.home() / ".config").resolve() / APP_CONFIG_DIR_NAME
    if _is_darwin() and not legacy.is_dir():
        return _macos_app_support_dir()
    return legacy


def default_config_yaml_path() -> Path:
    """Location of the YAML settings store (source of truth, see U21)."""
    return app_config_dir() / APP_CONFIG_YAML_NAME


def discover_env_file_paths() -> tuple[Path, ...]:
    """Existing ``.env`` files: app config dir first, then CWD (later entries override)."""
    candidates = (
        app_config_dir() / ".env",
        Path.cwd() / ".env",
    )
    return tuple(p for p in candidates if p.is_file())
