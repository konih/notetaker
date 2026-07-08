from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import TranscriptSegment
from live_meeting_transcriber.domain.ports import AudioSource
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
from live_meeting_transcriber.utils.time import utc_now
from typer.testing import CliRunner


@dataclass(frozen=True)
class _FakeConn:
    def close(self) -> None: ...


class _FakeDevices:
    def list_sources(self) -> list[AudioSource]:
        return []

    def get_default_monitor_source(self) -> str | None:
        return "sink.monitor"

    def get_default_microphone_source(self) -> str | None:
        return "alsa_input.fake"


class _FakeRecorder:
    def __init__(self, **_kwargs: object) -> None:
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
        on_segment: Callable[[TranscriptSegment], object],
    ) -> None:
        seg = TranscriptSegment(
            session_id=session_id,
            started_at=utc_now(),
            ended_at=utc_now() + timedelta(seconds=1),
            text="hello from test",
        )
        on_segment(seg)
        await asyncio.sleep(0)


class _FakeRecorderCtrlC:
    def __init__(self, **_kwargs: object) -> None:
        pass

    async def record_forever(self, **_kwargs: object) -> None:
        raise KeyboardInterrupt


def test_cli_record_uses_mocked_recorder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    settings = Settings(openai_api_key="x", database_url=f"sqlite:////{tmp_path}/db.sqlite3")

    container = Container(
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

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.Recorder", _FakeRecorder)

    result = CliRunner().invoke(app, ["record", "--title", "Test", "--chunk-seconds", "1"])
    assert result.exit_code == 0
    assert "hello from test" in result.stdout

    sessions = container.sessions.list()
    assert len(sessions) == 1
    assert sessions[0].title == "Test"


def test_cli_record_ctrl_c_exits_cleanly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    settings = Settings(openai_api_key="x", database_url=f"sqlite:////{tmp_path}/db.sqlite3")

    container = Container(
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

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.Recorder", _FakeRecorderCtrlC)

    result = CliRunner().invoke(app, ["record", "--title", "Test"])
    assert result.exit_code == 0
