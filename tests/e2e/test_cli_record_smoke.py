"""Smoke e2e: CLI record path with temp DB and mocked recorder (no ffmpeg/OpenAI)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import TranscriptSegment
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


@dataclass(frozen=True)
class _FakeDevices:
    def list_sources(self) -> list[object]:
        return []

    def get_default_monitor_source(self) -> str | None:
        return "sink.monitor"

    def get_default_microphone_source(self) -> str | None:
        return "alsa_input.fake"


class _FakeRecorder:
    def __init__(self, **_kwargs) -> None:
        pass

    async def record_forever(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        on_segment,
        **_kwargs,
    ) -> None:
        seg = TranscriptSegment(
            session_id=session_id,
            started_at=datetime.utcnow(),
            ended_at=datetime.utcnow() + timedelta(seconds=1),
            text="e2e smoke transcript",
        )
        on_segment(seg)
        await asyncio.sleep(0)


def _container(tmp_path, settings: Settings) -> Container:
    conn = open_connection(settings.database_url)
    return Container(
        settings=settings,
        _conn=conn,
        devices=_FakeDevices(),
        audio=None,  # type: ignore[arg-type]
        transcriber=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        diarization_segments=SqliteDiarizationRepository(conn),
        sessions=SqliteMeetingSessionRepository(conn),
        transcripts=SqliteTranscriptRepository(conn),
        summaries=SqliteSummaryRepository(conn),
        people=CompositeKnownPeopleRepository(
            inner=SqliteKnownPeopleRepository(conn),
            people_dir=None,
            person_template=None,
        ),
        session_speakers=SqliteSessionSpeakerNameRepository(conn),
    )


def test_cli_record_smoke_e2e(monkeypatch, tmp_path) -> None:
    db = tmp_path / "e2e.sqlite3"
    settings = Settings(OPENAI_API_KEY="test-key", DATABASE_URL=f"sqlite:////{db}")
    container = _container(tmp_path, settings)

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.Recorder", _FakeRecorder)

    result = CliRunner().invoke(app, ["record", "--title", "E2E Smoke", "--chunk-seconds", "1"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "e2e smoke transcript" in result.stdout

    sessions = container.sessions.list()
    assert len(sessions) == 1
    assert sessions[0].title == "E2E Smoke"
