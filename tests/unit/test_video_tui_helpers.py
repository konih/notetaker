"""Unit tests for meeting session type helpers and video import runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.video_import_service import (
    VideoImportError,
    VideoImportResult,
)
from live_meeting_transcriber.application.video_session_storage import is_video_import_session
from live_meeting_transcriber.transcription.openai_transcriber import OpenAITranscriptionError
from live_meeting_transcriber.ui.tui.meeting_session_helpers import (
    count_saved_slides,
    format_session_type_label,
    session_has_slide_source,
    session_is_video_import,
)
from live_meeting_transcriber.ui.tui.video_import_modal import (
    format_video_import_error,
    run_video_import,
)


def test_is_video_import_session_false_without_manifest(tmp_path: Path) -> None:
    sid = uuid4()
    assert is_video_import_session(tmp_path, sid) is False


def test_is_video_import_session_true_with_manifest(tmp_path: Path) -> None:
    sid = uuid4()
    manifest = tmp_path / "sessions" / str(sid) / "source_media.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"video_path": "/tmp/talk.mp4", "source": "/tmp/talk.mp4"}),
        encoding="utf-8",
    )
    assert is_video_import_session(tmp_path, sid) is True
    assert session_is_video_import(tmp_path, sid) is True


def test_format_session_type_label() -> None:
    assert format_session_type_label(is_video=True) == "▶ Video"
    assert format_session_type_label(is_video=False) == "● Live"


def test_session_has_slide_source_with_manifest(tmp_path: Path) -> None:
    sid = uuid4()
    manifest = tmp_path / "sessions" / str(sid) / "source_media.json"
    manifest.parent.mkdir(parents=True)
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"fake")
    manifest.write_text(
        json.dumps({"video_path": str(video), "source": str(video)}),
        encoding="utf-8",
    )
    assert session_has_slide_source(tmp_path, sid) is True


def test_session_has_slide_source_with_loose_mp4(tmp_path: Path) -> None:
    sid = uuid4()
    session_dir = tmp_path / "sessions" / str(sid)
    session_dir.mkdir(parents=True)
    (session_dir / "recording.mp4").write_bytes(b"fake")
    assert session_has_slide_source(tmp_path, sid) is True


def test_count_saved_slides(tmp_path: Path) -> None:
    sid = uuid4()
    slides_dir = tmp_path / "sessions" / str(sid) / "slides"
    slides_dir.mkdir(parents=True)
    (slides_dir / "001.png").write_bytes(b"x")
    (slides_dir / "002.png").write_bytes(b"y")
    assert count_saved_slides(tmp_path, sid) == 2


def test_format_video_import_error_wraps_generic() -> None:
    assert format_video_import_error(VideoImportError("bad source")) == "bad source"
    assert (
        format_video_import_error(
            OpenAITranscriptionError("Invalid OpenAI API key; check OPENAI_API_KEY")
        )
        == "Invalid OpenAI API key; check OPENAI_API_KEY"
    )
    assert "Video import failed" in format_video_import_error(RuntimeError("boom"))


@pytest.mark.asyncio
async def test_run_video_import_delegates_to_service() -> None:
    sid = uuid4()
    expected = VideoImportResult(
        session_id=sid,
        segment_count=3,
        slide_count=0,
        video_path=Path("/tmp/talk.mp4"),
    )
    mock_svc = MagicMock()
    mock_svc.import_video = AsyncMock(return_value=expected)
    container = MagicMock()

    with patch(
        "live_meeting_transcriber.ui.tui.video_import_modal.VideoImportService",
        return_value=mock_svc,
    ):
        result = await run_video_import(container, source="/tmp/talk.mp4", title="Talk")

    assert result == expected
    mock_svc.import_video.assert_awaited_once_with(
        source="/tmp/talk.mp4",
        title="Talk",
        extract_slides=False,
        on_progress=None,
    )
