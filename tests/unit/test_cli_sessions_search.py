"""F2: `sessions --search <text>` filters the listing; no flag lists everything."""

from __future__ import annotations

from pathlib import Path

import live_meeting_transcriber.cli.main as cli_main
import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.storage.people_composite import CompositeKnownPeopleRepository
from live_meeting_transcriber.storage.repositories import (
    SqliteDiarizationRepository,
    SqliteKnownPeopleRepository,
    SqliteMeetingSessionRepository,
    SqliteSessionSpeakerNameRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from typer.testing import CliRunner


def _container_with_sessions(tmp_path: Path) -> Container:
    settings = Settings(openai_api_key="x", database_url=f"sqlite:////{tmp_path}/db.sqlite3")
    conn = open_connection(settings.database_url)
    sessions = SqliteMeetingSessionRepository(conn)
    sessions.create(MeetingSession(title="Platform Review", attendees=["Konrad"]))
    sessions.create(MeetingSession(title="Budget Planning", notes="Q3 numbers"))
    return Container(
        settings=settings,
        _conn=conn,
        devices=None,  # type: ignore[arg-type]
        audio=None,  # type: ignore[arg-type]
        transcriber=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        diarization_segments=SqliteDiarizationRepository(conn),
        sessions=sessions,
        transcripts=SqliteTranscriptRepository(conn),
        summaries=SqliteSummaryRepository(conn),
        people=CompositeKnownPeopleRepository(
            inner=SqliteKnownPeopleRepository(conn),
            people_dir=None,
            person_template=None,
        ),
        session_speakers=SqliteSessionSpeakerNameRepository(conn),
    )


def _patch(monkeypatch: pytest.MonkeyPatch, container: Container) -> None:
    monkeypatch.setattr(cli_main, "load_settings", lambda: container.settings)
    monkeypatch.setattr(cli_main, "build_container", lambda _s: container)


def test_sessions_search_filters_by_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, _container_with_sessions(tmp_path))
    result = CliRunner().invoke(cli_main.app, ["sessions", "--search", "platform"])
    assert result.exit_code == 0
    assert "Platform Review" in result.stdout
    assert "Budget Planning" not in result.stdout


def test_sessions_search_matches_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, _container_with_sessions(tmp_path))
    result = CliRunner().invoke(cli_main.app, ["sessions", "--search", "numbers"])
    assert result.exit_code == 0
    assert "Budget Planning" in result.stdout
    assert "Platform Review" not in result.stdout


def test_sessions_without_search_lists_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch(monkeypatch, _container_with_sessions(tmp_path))
    result = CliRunner().invoke(cli_main.app, ["sessions"])
    assert result.exit_code == 0
    assert "Platform Review" in result.stdout
    assert "Budget Planning" in result.stdout
