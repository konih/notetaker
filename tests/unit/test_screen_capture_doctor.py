"""F6 — doctor check for live screen capture.

The macOS Screen Recording (TCC) permission cannot be verified headlessly, so the
check is honest about it: availability (platform + binary) is probed, the human
permission grant is surfaced as a reminder, never claimed as verified.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diagnostics.screen_capture_doctor import check_live_screen_capture


class _Screen:
    def __init__(self, ok: bool, reason: str | None) -> None:
        self._result = (ok, reason)

    def availability(self) -> tuple[bool, str | None]:
        return self._result

    def capture(self, output_path: Path) -> bool:  # pragma: no cover - not used
        return False


def _settings(**overrides: object) -> Settings:
    return Settings(openai_api_key="k", database_url="sqlite:////tmp/t.db", **overrides)  # type: ignore[arg-type]


def test_disabled_capture_is_ok_and_says_so() -> None:
    result = check_live_screen_capture(_settings(), screen=_Screen(True, None))
    assert result.ok is True
    assert "disabled" in result.detail.lower()


def test_enabled_but_unavailable_fails_with_remediation() -> None:
    result = check_live_screen_capture(
        _settings(live_screen_capture_enabled=True),
        screen=_Screen(False, "live screen capture requires macOS"),
    )
    assert result.ok is False
    assert "macOS" in result.detail
    assert result.remediation is not None


def test_enabled_and_available_reminds_about_tcc_grant() -> None:
    result = check_live_screen_capture(
        _settings(live_screen_capture_enabled=True), screen=_Screen(True, None)
    )
    assert result.ok is True
    assert "Screen Recording" in result.detail  # human TCC grant cannot be auto-verified


def test_doctor_cli_includes_screen_capture_line(monkeypatch) -> None:
    import live_meeting_transcriber.diagnostics.diarization_doctor as doc

    monkeypatch.setattr(doc, "run_diarization_checks", lambda settings: [])
    monkeypatch.setattr(
        "live_meeting_transcriber.cli.commands.finalize.load_settings",
        lambda: _settings(),
        raising=False,
    )
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert "Live screen capture" in result.output
