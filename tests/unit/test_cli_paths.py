"""F5: `live-transcriber paths` prints resolved config/data locations.

The macOS installer (packaging/install-macos.sh) and support workflows need a
single source of truth for "where does the app read config / keep data" —
duplicated rules in shell scripts drift. The command must work without any
provider configuration (no OPENAI_API_KEY), like `doctor`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.paths import app_config_dir
from typer.testing import CliRunner

runner = CliRunner()


def test_paths_runs_without_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = runner.invoke(app, ["paths"])
    assert result.exit_code == 0, result.output


def test_paths_lists_config_and_data_locations(tmp_path: Path) -> None:
    result = runner.invoke(app, ["paths"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert str(app_config_dir()) in out
    assert "Config directory" in out
    assert "Data directory" in out
    assert "Database URL" in out
    assert "Log file" in out


def test_paths_config_dir_flag_is_machine_readable() -> None:
    result = runner.invoke(app, ["paths", "--config-dir"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == str(app_config_dir())
