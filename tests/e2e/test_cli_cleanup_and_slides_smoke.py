"""E2e smoke: cleanup CLI and slide preview without re-transcribe."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.video_import_service import VideoImportService
from live_meeting_transcriber.audio.media_import import FfmpegMediaImporter
from live_meeting_transcriber.audio.session_recording import FfmpegSessionAudioStore
from live_meeting_transcriber.audio.wav_ops import FfmpegWavOps
from live_meeting_transcriber.cli.main import app
from live_meeting_transcriber.video.tools import FfmpegSlideDetectionTools
from typer.testing import CliRunner

from tests.e2e.cli_helpers import FakeTranscriber, build_e2e_container
from tests.e2e.video_helpers import (
    ffmpeg_available,
    patch_data_dir,
    slide_seconds_for_settings,
    video_import_settings,
)


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_cli_cleanup_orphans_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = build_e2e_container(tmp_path, settings, transcriber=FakeTranscriber())

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
    container = build_e2e_container(tmp_path, settings, transcriber=FakeTranscriber())

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
    container = build_e2e_container(tmp_path, settings, transcriber=FakeTranscriber())
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

    sessions_before = len(container.sessions.list())
    segments_before = len(container.transcripts.list_by_session(result.session_id))

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

    # Persisted-state depth (T4) + performance NFR (AGENTS.md): preview re-runs slide
    # *detection* only — it must not re-transcribe, append segments, or create sessions.
    assert len(container.sessions.list()) == sessions_before
    assert len(container.transcripts.list_by_session(result.session_id)) == segments_before


@pytest.mark.skipif(
    not ffmpeg_available(), reason="requires the ffmpeg binary (real video encode/probe)"
)
def test_preview_threshold_changes_candidate_count(
    monkeypatch: pytest.MonkeyPatch, sample_video: Path, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    settings = video_import_settings(tmp_path)
    container = build_e2e_container(tmp_path, settings, transcriber=FakeTranscriber())
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
