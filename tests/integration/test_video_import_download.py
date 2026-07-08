"""Integration: import an English presentation URL via transcribe-video (mocked STT)."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from live_meeting_transcriber.application.video_import_service import VideoImportService
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from tests.e2e.video_helpers import ffmpeg_available, patch_data_dir, video_import_settings


@dataclass(frozen=True)
class _FakeTranscriber:
    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text="integration transcript line",
        )


def _ytdlp_available() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], check=True, capture_output=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.integration
@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
@pytest.mark.skipif(not _ytdlp_available(), reason="yt-dlp not available")
def test_transcribe_video_from_downloaded_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_data_dir(monkeypatch, tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    out = cache_dir / "presentation_en_source.mp4"
    # English tech presentation with slides (see tests/fixtures/README.md).
    url = "https://www.youtube.com/watch?v=DZL-ExKPjnc"

    subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "-f",
            "best[height<=360][ext=mp4]/best[ext=mp4]/best",
            "--merge-output-format",
            "mp4",
            "-o",
            str(out),
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.is_file()

    settings = video_import_settings(
        tmp_path,
        VIDEO_SLIDE_MIN_INTERVAL_SECONDS=5.0,
        VIDEO_SLIDE_MAX_CANDIDATES=10,
    )

    conn = open_connection(settings.database_url)
    svc = VideoImportService(
        settings=settings,
        sessions=SqliteMeetingSessionRepository(conn),
        transcripts=SqliteTranscriptRepository(conn),
        transcriber=_FakeTranscriber(),
    )

    result = asyncio.run(
        svc.import_video(
            source=url,
            title="Presentation EN integration",
            accept_all_slides=True,
        )
    )

    assert result.segment_count >= 1
    assert result.slide_count >= 1

    segments = SqliteTranscriptRepository(conn).list_by_session(result.session_id)
    assert len(segments) >= 1
    conn.close()
