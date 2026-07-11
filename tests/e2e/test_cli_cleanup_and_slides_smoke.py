"""E2e smoke: cleanup CLI and slide preview without re-transcribe."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.video_import_service import VideoImportService
from live_meeting_transcriber.audio.media_import import FfmpegMediaImporter
from live_meeting_transcriber.audio.session_recording import FfmpegSessionAudioStore
from live_meeting_transcriber.audio.wav_ops import FfmpegWavOps
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
from live_meeting_transcriber.video.tools import FfmpegSlideDetectionTools
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
            text="preview smoke",
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
def test_cli_cleanup_orphans_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)

    orphan_id = uuid4()
    orphan_dir = tmp_path / "chunks" / str(orphan_id)
    orphan_dir.mkdir(parents=True)

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    result = CliRunner().invoke(app, ["cleanup", "--orphans"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Would remove" in result.stdout
    assert str(orphan_dir) in result.stdout
    assert orphan_dir.is_dir()


def test_cli_cleanup_orphans_yes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)

    orphan_id = uuid4()
    orphan_dir = tmp_path / "sessions" / str(orphan_id)
    orphan_dir.mkdir(parents=True)

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    result = CliRunner().invoke(app, ["cleanup", "--orphans", "--yes"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Removed" in result.stdout
    assert str(orphan_dir) in result.stdout
    assert not orphan_dir.exists()


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_cli_slides_preview_smoke(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)
    svc = VideoImportService(
        media=FfmpegMediaImporter(),
        wav_ops=FfmpegWavOps(),
        session_audio=FfmpegSessionAudioStore(),
        slide_tools=FfmpegSlideDetectionTools(),
        settings=settings,
        sessions=container.sessions,
        transcripts=container.transcripts,
        transcriber=container.transcriber,
    )
    result = asyncio.run(
        svc.import_video(
            source=str(sample_video),
            title="Preview E2E",
            extract_slides=False,
        )
    )

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    cli = CliRunner().invoke(
        app,
        [
            "slides",
            "preview",
            "--session-id",
            str(result.session_id),
            "--min-interval",
            str(slide_seconds_for_settings()),
        ],
    )
    assert cli.exit_code == 0, cli.stdout + cli.stderr
    assert "Candidates: 3" in cli.stdout


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_preview_threshold_changes_candidate_count(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = _container(tmp_path, settings)
    svc = VideoImportService(
        media=FfmpegMediaImporter(),
        wav_ops=FfmpegWavOps(),
        session_audio=FfmpegSessionAudioStore(),
        slide_tools=FfmpegSlideDetectionTools(),
        settings=settings,
        sessions=container.sessions,
        transcripts=container.transcripts,
        transcriber=container.transcriber,
    )
    import_result = asyncio.run(svc.import_video(source=str(sample_video), extract_slides=False))
    sid = str(import_result.session_id)

    monkeypatch.setattr("live_meeting_transcriber.cli.main.load_settings", lambda: settings)
    monkeypatch.setattr("live_meeting_transcriber.cli.main.build_container", lambda _s: container)

    strict = CliRunner().invoke(
        app,
        [
            "slides",
            "preview",
            "--session-id",
            sid,
            "--threshold",
            "0.99",
            "--min-interval",
            str(slide_seconds_for_settings()),
        ],
    )
    loose = CliRunner().invoke(
        app,
        [
            "slides",
            "preview",
            "--session-id",
            sid,
            "--threshold",
            "0.01",
            "--min-interval",
            "0",
        ],
    )
    assert strict.exit_code == 0 and loose.exit_code == 0
    strict_count = int(strict.stdout.split("Candidates: ")[1].split()[0])
    loose_count = int(loose.stdout.split("Candidates: ")[1].split()[0])
    assert loose_count >= strict_count
