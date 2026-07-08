"""UI-managed audio device preferences, persisted as JSON next to ``.env``.

These are chosen from the TUI (Audio sources menu) and take effect on the next
recording. They override the environment/default source resolution but are kept
separate from ``.env`` so hand-edited config comments are never rewritten.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from live_meeting_transcriber.config.settings import app_config_dir

DEVICE_PREFS_FILENAME = "device_prefs.json"


class DevicePrefs(BaseModel):
    """Persisted audio-source selection. ``None`` means "not configured — use defaults"."""

    model_config = {"frozen": True}

    monitor_source: str | None = None
    microphone_source: str | None = None


def device_prefs_path() -> Path:
    return app_config_dir() / DEVICE_PREFS_FILENAME


def load_device_prefs() -> DevicePrefs:
    """Load saved device preferences; return empty prefs if the file is missing or unreadable."""
    path = device_prefs_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return DevicePrefs()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return DevicePrefs()
        return DevicePrefs.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return DevicePrefs()


def save_device_prefs(prefs: DevicePrefs) -> Path:
    """Persist device preferences atomically; creates the config dir if needed."""
    path = device_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(prefs.model_dump(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
