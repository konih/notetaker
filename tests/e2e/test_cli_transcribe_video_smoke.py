"""E2e smoke: transcribe-video with generated sample MP4 and mocked STT."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.video_import_service import VideoImportService
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
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

from tests.e2e.video_helpers import (
    ffmpeg_available,
    generate_sample_video,
    patch_data_dir,
    slide_seconds_for_settings,
    video_import_settings,
)


@dataclass(frozen=True)
class _FakeTranscriber:
    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text=f"chunk at {chunk.started_at.isoformat()}",
        )


def _container(tmp_path: Path, settings: Settings) -> Container:
    conn = open_connection(settings.database_url)
    return Container(
        settings=settings,
        _conn=conn,
        devices=None,  # type: ignore[arg-type]
        audio=None,  # type: ignore[arg-type]
        transcriber=_FakeTranscriber(),
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


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    if not ffmpeg_available():
        pytest.skip("requires the ffmpeg binary (real video encode/probe)")
    dest = tmp_path / "sample_presentation.mp4"
    return generate_sample_video(dest, slide_seconds=15.0)


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_video_import_service_e2e(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)
    svc = VideoImportService(
        settings=settings,
        sessions=container.sessions,
        transcripts=container.transcripts,
        transcriber=container.transcriber,
    )

    result = asyncio.run(
        svc.import_video(
            source=str(sample_video),
            title="E2E Sample Talk",
            accept_all_slides=True,
        )
    )

    assert result.segment_count >= 1
    assert result.slide_count == 3

    segments = container.transcripts.list_by_session(result.session_id)
    assert len(segments) >= 1

    slides_dir = tmp_path / "sessions" / str(result.session_id) / "slides"
    assert slides_dir.is_dir()
    pngs = list(slides_dir.glob("slide_*.png"))
    assert len(pngs) == 3
    assert (slides_dir / "slides.json").is_file()

    full_wav = tmp_path / "sessions" / str(result.session_id) / "full_session.wav"
    assert full_wav.is_file()


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_cli_transcribe_video_smoke_e2e(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    result = CliRunner().invoke(
        app,
        [
            "transcribe-video",
            "--source",
            str(sample_video),
            "--title",
            "CLI E2E Slides",
            "--yes-slides",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Session:" in result.stdout
    assert "slides saved: 3" in result.stdout

    sessions = container.sessions.list()
    assert len(sessions) == 1
    assert sessions[0].title == "CLI E2E Slides"


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_slide_detection_finds_three_slides_on_sample(sample_video: Path) -> None:
    from live_meeting_transcriber.audio.media_import import probe_media_duration_seconds
    from live_meeting_transcriber.video.slide_detection import detect_slide_candidates

    duration = probe_media_duration_seconds(sample_video)
    assert duration >= slide_seconds_for_settings() * 2

    candidates = detect_slide_candidates(
        video_path=sample_video,
        duration_seconds=duration,
        sample_interval_seconds=2.0,
        change_threshold=0.08,
        min_slide_interval_seconds=slide_seconds_for_settings(),
        max_candidates=10,
        preview_dir=None,
    )
    assert len(candidates) == 3
    assert candidates[0].timestamp_seconds == 0.0
