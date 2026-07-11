"""Filesystem locations for config and data (XDG-aware), shared by all settings areas.

Split out of ``config/settings.py`` (A8) so per-area section models can use the
path helpers without importing the aggregate ``Settings`` model.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_CONFIG_DIR_NAME = "live-meeting-transcriber"
APP_DATA_DIR_NAME = "live-meeting-transcriber"

APP_CONFIG_YAML_NAME = "config.yaml"


def default_data_dir() -> Path:
    return (Path.home() / ".local" / "share" / APP_DATA_DIR_NAME).resolve()


def default_database_url() -> str:
    return f"sqlite:////{default_data_dir() / 'app.db'}"


def xdg_config_home() -> Path:
    """XDG base directory for user-specific configuration (``$XDG_CONFIG_HOME`` or ``~/.config``)."""
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".config").resolve()


def app_config_dir() -> Path:
    return xdg_config_home() / APP_CONFIG_DIR_NAME


def default_config_yaml_path() -> Path:
    """Location of the YAML settings store (source of truth, see U21)."""
    return app_config_dir() / APP_CONFIG_YAML_NAME


def discover_env_file_paths() -> tuple[Path, ...]:
    """Existing ``.env`` files: XDG config dir first, then CWD (later entries override)."""
    candidates = (
        app_config_dir() / ".env",
        Path.cwd() / ".env",
    )
    return tuple(p for p in candidates if p.is_file())
