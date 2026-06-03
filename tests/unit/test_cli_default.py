from __future__ import annotations

from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from typer.testing import CliRunner


class _FakeContainer:
    def close(self) -> None:
        return None


def test_cli_no_args_launches_tui(monkeypatch, tmp_path) -> None:
    settings = Settings(OPENAI_API_KEY="x", DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3")
    called: dict[str, bool] = {}

    def fake_run_tui_attached(**kwargs: object) -> None:
        called["tui"] = True

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr(
        "live_meeting_transcriber.cli.main.build_container",
        lambda _s: _FakeContainer(),
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.ui.tui.app.run_tui_attached",
        fake_run_tui_attached,
    )

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert called.get("tui") is True


def test_cli_help_without_subcommand() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Live background meeting transcription" in result.stdout
