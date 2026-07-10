"""F9: the `doctor` CLI command renders prerequisite checks and exits accordingly."""

from __future__ import annotations

import pytest
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.diagnostics import diarization_doctor as doc
from typer.testing import CliRunner

runner = CliRunner()


def _patch_checks(monkeypatch: pytest.MonkeyPatch, results: list[doc.CheckResult]) -> None:
    monkeypatch.setattr(doc, "run_diarization_checks", lambda _settings: results)


def test_doctor_all_ok_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_checks(
        monkeypatch,
        [
            doc.CheckResult("WhisperX + pyannote extras", True, "importable"),
            doc.CheckResult("Hugging Face token", True, "authenticated as koniheimel"),
        ],
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "WhisperX + pyannote extras" in result.output
    assert "koniheimel" in result.output


def test_doctor_failure_exits_one_and_shows_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_checks(
        monkeypatch,
        [
            doc.CheckResult("WhisperX + pyannote extras", True, "importable"),
            doc.CheckResult(
                "Hugging Face token",
                False,
                "HF_TOKEN is set but invalid/rejected",
                "Regenerate the token at https://huggingface.co/settings/tokens",
            ),
        ],
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1, result.output
    # remediation for the failing check is surfaced
    assert "Regenerate the token" in result.output
    # names the first failing check
    assert "Hugging Face token" in result.output
