"""Shared helpers for transcribe-video e2e tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from live_meeting_transcriber.config.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]


def generate_sample_video(path: Path, *, slide_seconds: float = 15.0) -> Path:
    script = _REPO_ROOT / "scripts" / "generate_sample_video.py"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "-o",
            str(path),
            "--slide-seconds",
            str(slide_seconds),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def video_import_settings(tmp_path: Path, **overrides: object) -> Settings:
    """Settings tuned for fast slide e2e (short intervals, temp DB)."""
    db = tmp_path / "test.sqlite3"
    base: dict[str, object] = {
        "OPENAI_API_KEY": "test-key",
        "DATABASE_URL": f"sqlite:////{db}",
        "VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS": 2.0,
        "VIDEO_SLIDE_CHANGE_THRESHOLD": 0.08,
        "VIDEO_SLIDE_MIN_INTERVAL_SECONDS": slide_seconds_for_settings(),
        "VIDEO_SLIDE_MAX_CANDIDATES": 20,
        "KEEP_AUDIO_CHUNKS": True,
        "AUDIO_CHUNK_SECONDS": 5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def patch_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Route Settings.ensure_data_dir() to a pytest tmp_path."""

    def _ensure(_self: Settings) -> Path:
        return tmp_path

    monkeypatch.setattr(Settings, "ensure_data_dir", _ensure)


def slide_seconds_for_settings() -> float:
    return 12.0


def ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
