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
    settings = Settings(openai_api_key="test-key", database_url=f"sqlite:////{db}")
    container = build_e2e_container(tmp_path, settings)
    patch_cli(monkeypatch, settings=settings, container=container)
    patch_fake_recorder(monkeypatch)

    result = CliRunner().invoke(app, ["record", "--title", "E2E Smoke", "--chunk-seconds", "1"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "e2e smoke transcript" in result.stdout

    # Persisted-state depth (T5): the record workflow must leave a durable session AND a
    # persisted transcript AND a set ended_at — not just print a line. A dangling ended_at
    # (=NULL) was the B4/B2 data-loss class, so we assert the session was properly closed.
    sessions = container.sessions.list()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.title == "E2E Smoke"
    assert session.ended_at is not None, "record must set ended_at (interrupted-session guard)"

    persisted = container.transcripts.list_by_session(session.id)
    assert [seg.text for seg in persisted] == ["e2e smoke transcript"], (
        "the streamed segment must be persisted to the transcript repo, not only echoed"
    )
