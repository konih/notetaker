"""F3 (ROUGH-02): a provider misconfiguration must surface as a clear CLI message.

Every command builds the container in ``_main_callback``; a missing
``OPENAI_API_KEY`` used to escape as an unhandled ``ProviderSelectionError``
(full Python traceback, exit code 1). It should instead print an actionable
one-line message to stderr and exit with code 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.application.container import ProviderSelectionError
from live_meeting_transcriber.config.settings import Settings
from typer.testing import CliRunner

import live_meeting_transcriber.cli.main as cli_main


def _openai_no_key_settings(tmp_path: Path) -> Settings:
    return Settings(
        openai_api_key=None,
        transcription_provider="openai",
        database_url=f"sqlite:////{tmp_path}/db.sqlite3",
    )


def test_missing_openai_key_exits_cleanly_without_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli_main, "load_settings", lambda: _openai_no_key_settings(tmp_path))

    result = CliRunner().invoke(cli_main.app, ["sessions"])

    # Exit 2 (matches the file's other misconfiguration exits), not a crash.
    assert result.exit_code == 2
    # The raw provider error must not leak as an unhandled exception/traceback.
    assert not isinstance(result.exception, ProviderSelectionError)


def test_missing_openai_key_message_is_actionable_on_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli_main, "load_settings", lambda: _openai_no_key_settings(tmp_path))

    result = CliRunner().invoke(cli_main.app, ["sessions"])

    # Error belongs on stderr, not stdout (Click >=8.2 separates the streams).
    assert "OPENAI_API_KEY" in result.stderr
    # Remediation must point at a keyless alternative, not config.yaml (a secret
    # is never written to YAML — U21/AGENTS.md).
    assert "faster_whisper" in result.stderr
