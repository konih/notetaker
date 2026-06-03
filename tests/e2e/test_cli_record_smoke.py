"""Smoke e2e: CLI record path with temp DB and mocked recorder (no ffmpeg/OpenAI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from typer.testing import CliRunner

from tests.e2e.cli_helpers import build_e2e_container, patch_cli, patch_fake_recorder


def test_cli_record_smoke_e2e(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "e2e.sqlite3"
    settings = Settings(OPENAI_API_KEY="test-key", DATABASE_URL=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)
    patch_cli(monkeypatch, settings=settings, container=container)
    patch_fake_recorder(monkeypatch)

    result = CliRunner().invoke(app, ["record", "--title", "E2E Smoke", "--chunk-seconds", "1"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "e2e smoke transcript" in result.stdout

    sessions = container.sessions.list()
    assert len(sessions) == 1
    assert sessions[0].title == "E2E Smoke"
