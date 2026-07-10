"""D4: `record` warns up-front when AUDIO_STEREO_MODE=dual_path will silently downgrade.

Today the only signal is a per-chunk log emitted every ~10s once recording is already
running. This asserts the operator is told *before* the session starts, on stderr.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from typer.testing import CliRunner

from tests.e2e.cli_helpers import build_e2e_container, patch_cli, patch_fake_recorder


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **settings_kwargs: object) -> object:
    db = tmp_path / "e2e.sqlite3"
    settings = Settings(
        openai_api_key="test-key",
        database_url=f"sqlite:////{db}",
        **settings_kwargs,  # type: ignore[arg-type]
    )
    container = build_e2e_container(tmp_path, settings)
    patch_cli(monkeypatch, settings=settings, container=container)
    patch_fake_recorder(monkeypatch)
    return CliRunner().invoke(app, ["record", "--title", "DP", "--chunk-seconds", "1"])


def test_dual_path_without_faster_whisper_warns_on_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # e2e container uses transcriber=None (no transcribe_stereo_chunk) → dual_path is inert.
    result = _run(monkeypatch, tmp_path, audio_stereo_mode="dual_path", audio_channels=2)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "AUDIO_STEREO_MODE=dual_path" in result.stderr


def test_mixdown_does_not_warn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _run(monkeypatch, tmp_path, audio_stereo_mode="mixdown", audio_channels=1)
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "AUDIO_STEREO_MODE=dual_path" not in result.stderr
