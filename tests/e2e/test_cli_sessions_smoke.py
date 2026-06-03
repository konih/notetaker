"""E2e smoke: sessions CLI lists a session created via mocked record."""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from typer.testing import CliRunner

from tests.e2e.cli_helpers import build_e2e_container, patch_cli, patch_fake_recorder


def test_cli_sessions_smoke_e2e(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "sessions.sqlite3"
    settings = Settings(OPENAI_API_KEY="test-key", DATABASE_URL=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)
    patch_cli(monkeypatch, settings=settings, container=container)
    patch_fake_recorder(monkeypatch)

    record_result = CliRunner().invoke(
        app,
        ["record", "--title", "Listed Session", "--chunk-seconds", "1"],
    )
    assert record_result.exit_code == 0, record_result.stdout + record_result.stderr
    assert "e2e smoke transcript" in record_result.stdout

    sessions = container.sessions.list()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.title == "Listed Session"

    result = CliRunner().invoke(app, ["sessions"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Listed Session" in result.stdout
    assert str(session.id) in result.stdout
