"""Integration: transcribe-video import pipeline with the download boundary mocked.

Exercises ``VideoImportService`` end-to-end — download seam -> slide extraction ->
chunked ASR -> SQLite persistence — against **real ffmpeg** and a **committed fixture
video**, but replaces the network download (yt-dlp against a live YouTube URL) with a
deterministic stub. The original test downloaded a real URL, so it never ran in CI
(``RUN_INTEGRATION_TESTS`` unset) and was network-flaky; this version is the
deterministic integration lane (C3 / test-pyramid Phase 2). Kept ``@pytest.mark.integration``
so it stays counted as the integration layer (T5 drift-guard) and runs in CI's ``integration``
job (which installs ffmpeg).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from live_meeting_transcriber.application import video_import_service as vis
from live_meeting_transcriber.application.video_import_service import VideoImportService
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from tests.e2e.video_helpers import ffmpeg_available, patch_data_dir, video_import_settings

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "video" / "presentation_en_15s_360p.mp4"
)


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


@pytest.mark.integration
@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
def test_transcribe_video_from_downloaded_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert _FIXTURE.is_file(), f"missing committed fixture video: {_FIXTURE}"
    patch_data_dir(monkeypatch, tmp_path)

    # An English tech presentation with slides. Resolving it "downloads" to the fixture.
    url = "https://www.youtube.com/watch?v=DZL-ExKPjnc"
    resolved_sources: list[str] = []

    def _fake_resolve(*, source: str, download_dir: Path) -> Path:
        # Stand in for yt-dlp: record the requested source, place the fixture where a
        # real download would have landed, and return that path.
        resolved_sources.append(source)
        dest = download_dir / _FIXTURE.name
        dest.write_bytes(_FIXTURE.read_bytes())
        return dest

    monkeypatch.setattr(vis, "resolve_media_source", _fake_resolve)

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

    # The URL was routed through the (mocked) download seam, then the real pipeline ran.
    assert resolved_sources == [url]
    assert result.segment_count >= 1
    assert result.slide_count >= 1

    segments = SqliteTranscriptRepository(conn).list_by_session(result.session_id)
    assert len(segments) >= 1
    conn.close()
