from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings


@dataclass(frozen=True)
class _FakeConn:
    def close(self) -> None: ...


@dataclass(frozen=True)
class _Src:
    name: str
    description: str = ""


class _FakeDevices:
    def list_sources(self) -> list[_Src]:
        return [_Src(name="sink.monitor"), _Src(name="mic")]

    def get_default_monitor_source(self) -> str | None:
        return "sink.monitor"


def test_cli_devices_lists_sources(monkeypatch, tmp_path) -> None:
    settings = Settings(OPENAI_API_KEY="x", DATABASE_URL=f"sqlite:////{tmp_path}/db.sqlite3")
    container = Container(
        settings=settings,
        _conn=_FakeConn(),
        devices=_FakeDevices(),
        audio=None,  # type: ignore[arg-type]
        transcriber=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        transcripts=None,  # type: ignore[arg-type]
        summaries=None,  # type: ignore[arg-type]
    )

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    result = CliRunner().invoke(app, ["devices"])
    assert result.exit_code == 0
    assert "* sink.monitor" in result.stdout
    assert "  mic" in result.stdout

