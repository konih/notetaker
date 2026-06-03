from __future__ import annotations

import shutil
import wave
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.slide_review import (
    format_timestamp,
    review_slide_candidates,
)
from live_meeting_transcriber.application.video_import_service import (
    VideoImportService,
    _effective_video_chunk_seconds,
    _planned_chunk_count,
)
from live_meeting_transcriber.audio.media_source import is_remote_url, media_title_from_source
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import AudioChunk, SlideCandidate, TranscriptSegment
from live_meeting_transcriber.transcription.openai_transcriber import OpenAITranscriptionError
from live_meeting_transcriber.video.strategies.frame_diff import mean_absolute_difference


def _write_silent_wav(path: Path, *, seconds: float, rate: int = 16000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds * channels))


@dataclass
class _RecordingTranscriber:
    calls: list[AudioChunk] = field(default_factory=list)

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        self.calls.append(chunk)
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text="ok",
        )


def test_effective_video_chunk_seconds_short_file() -> None:
    assert (
        _effective_video_chunk_seconds(30.0, configured_chunk_seconds=10, implicit_chunk=True)
        == 30.0
    )


def test_effective_video_chunk_seconds_implicit_up_to_120s() -> None:
    assert (
        _effective_video_chunk_seconds(120.0, configured_chunk_seconds=10, implicit_chunk=True)
        == 120.0
    )


def test_effective_video_chunk_seconds_explicit_chunking() -> None:
    assert (
        _effective_video_chunk_seconds(120.0, configured_chunk_seconds=10, implicit_chunk=False)
        == 10.0
    )


@pytest.mark.asyncio
async def test_transcribe_wav_in_chunks_single_request_for_short_video(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    full_wav = tmp_path / "full.wav"
    _write_silent_wav(full_wav, seconds=30.0)
    chunk_dir = tmp_path / "chunks"
    transcriber = _RecordingTranscriber()
    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=MagicMock(),
        transcripts=MagicMock(),
        transcriber=transcriber,
    )
    session_id = uuid4()

    from datetime import UTC, datetime

    summary = await svc._transcribe_wav_in_chunks(
        session_id=session_id,
        full_wav=full_wav,
        duration_seconds=30.0,
        chunk_seconds=30.0,
        sample_rate_hz=16000,
        channels=1,
        chunk_dir=chunk_dir,
        session_started_at=datetime.now(tz=UTC),
        on_segment=None,
        on_progress=None,
    )
    assert summary.segments == 1
    assert summary.chunks == 1
    assert len(transcriber.calls) == 1


@pytest.mark.asyncio
async def test_transcribe_wav_in_chunks_skips_sub_minimum_tail(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    full_wav = tmp_path / "full.wav"
    _write_silent_wav(full_wav, seconds=120.064)
    chunk_dir = tmp_path / "chunks"
    transcriber = _RecordingTranscriber()
    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=MagicMock(),
        transcripts=MagicMock(),
        transcriber=transcriber,
    )
    session_id = uuid4()

    from datetime import UTC, datetime

    summary = await svc._transcribe_wav_in_chunks(
        session_id=session_id,
        full_wav=full_wav,
        duration_seconds=120.064,
        chunk_seconds=10.0,
        sample_rate_hz=16000,
        channels=1,
        chunk_dir=chunk_dir,
        session_started_at=datetime.now(tz=UTC),
        on_segment=None,
        on_progress=None,
    )
    assert summary.segments == 12
    assert summary.chunks == 12
    assert len(transcriber.calls) == 12


@pytest.mark.asyncio
async def test_import_video_preview_only_skips_transcribe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"not-a-real-video")

    transcriber = AsyncMock()
    sessions = MagicMock()
    session = MagicMock()
    session.id = uuid4()
    session.started_at = MagicMock()
    sessions.create.return_value = session

    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=sessions,
        transcripts=MagicMock(),
        transcriber=transcriber,
    )

    def _resolve(*_a, **_k):
        return video

    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.resolve_media_source",
        _resolve,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.probe_media_duration_seconds",
        lambda _p: 45.0,
    )

    def _extract(**kwargs):
        dest = kwargs["dest_wav"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_silent_wav(dest, seconds=45.0)

    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.extract_audio_to_wav",
        _extract,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.write_source_media_manifest",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.append_timeline_entry",
        lambda *_a, **_k: None,
    )

    result = await svc.import_video(
        source=str(video),
        extract_slides=False,
        skip_transcription=True,
    )
    assert result.segment_count == 0
    transcriber.transcribe.assert_not_called()


def test_is_remote_url() -> None:
    assert is_remote_url("https://www.youtube.com/watch?v=abc")
    assert is_remote_url("http://example.com/v.mp4")
    assert not is_remote_url("/tmp/video.mp4")
    assert not is_remote_url("video.mp4")


def test_media_title_from_source_local() -> None:
    from pathlib import Path

    title = media_title_from_source("/tmp/my_talk.mp4", Path("/tmp/my_talk.mp4"))
    assert title == "my talk"


def test_format_timestamp() -> None:
    assert format_timestamp(65) == "1:05"
    assert format_timestamp(3661) == "1:01:01"


def test_review_slide_candidates_accept_all() -> None:
    cands = [
        SlideCandidate(timestamp_seconds=0.0, change_score=1.0),
        SlideCandidate(timestamp_seconds=30.0, change_score=0.5),
    ]
    out = review_slide_candidates(cands, accept_all=True)
    assert len(out) == 2


def test_review_slide_candidates_reject_all() -> None:
    cands = [SlideCandidate(timestamp_seconds=0.0, change_score=1.0)]
    assert review_slide_candidates(cands, reject_all=True) == []


def test_review_slide_candidates_interactive() -> None:
    cands = [
        SlideCandidate(timestamp_seconds=0.0, change_score=1.0),
        SlideCandidate(timestamp_seconds=30.0, change_score=0.5),
        SlideCandidate(timestamp_seconds=60.0, change_score=0.4),
    ]
    answers = iter(["y", "n", "y"])
    lines: list[str] = []

    out = review_slide_candidates(
        cands,
        prompt_fn=lambda _p: next(answers),
        echo_fn=lines.append,
    )
    assert len(out) == 2
    assert out[0].timestamp_seconds == 0.0
    assert out[1].timestamp_seconds == 60.0


def test_planned_chunk_count_200s_video() -> None:
    assert _planned_chunk_count(200.0, 10.0) == 20


@pytest.mark.asyncio
async def test_transcribe_wav_in_chunks_200s_processes_all_chunks(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    full_wav = tmp_path / "full.wav"
    _write_silent_wav(full_wav, seconds=200.0)
    chunk_dir = tmp_path / "chunks"
    transcriber = _RecordingTranscriber()
    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=MagicMock(),
        transcripts=MagicMock(),
        transcriber=transcriber,
    )
    session_id = uuid4()

    from datetime import UTC, datetime

    summary = await svc._transcribe_wav_in_chunks(
        session_id=session_id,
        full_wav=full_wav,
        duration_seconds=200.0,
        chunk_seconds=10.0,
        sample_rate_hz=16000,
        channels=1,
        chunk_dir=chunk_dir,
        session_started_at=datetime.now(tz=UTC),
        on_segment=None,
        on_progress=None,
    )
    assert summary.chunks == 20
    assert summary.segments == 20
    assert len(transcriber.calls) == 20


@dataclass
class _FailingAfterFirstTranscriber:
    calls: list[AudioChunk] = field(default_factory=list)

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        self.calls.append(chunk)
        if len(self.calls) > 1:
            raise OpenAITranscriptionError("OpenAI rate limit reached; wait and retry")
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text="first chunk only",
        )


@pytest.mark.asyncio
async def test_transcribe_wav_in_chunks_api_failure_returns_partial_summary(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    full_wav = tmp_path / "full.wav"
    _write_silent_wav(full_wav, seconds=30.0)
    chunk_dir = tmp_path / "chunks"
    transcriber = _FailingAfterFirstTranscriber()
    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=MagicMock(),
        transcripts=MagicMock(),
        transcriber=transcriber,
    )
    session_id = uuid4()

    from datetime import UTC, datetime

    summary = await svc._transcribe_wav_in_chunks(
        session_id=session_id,
        full_wav=full_wav,
        duration_seconds=30.0,
        chunk_seconds=10.0,
        sample_rate_hz=16000,
        channels=1,
        chunk_dir=chunk_dir,
        session_started_at=datetime.now(tz=UTC),
        on_segment=None,
        on_progress=None,
    )
    assert summary.segments == 1
    assert summary.failed == 2
    assert summary.chunks == 3
    assert summary.has_failures
    assert summary.status_message() is not None
    assert "Partial transcription" in summary.status_message()
    assert len(transcriber.calls) == 3


@pytest.mark.asyncio
async def test_import_video_raises_when_all_chunks_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"not-a-real-video")

    transcriber = AsyncMock()
    transcriber.transcribe = AsyncMock(
        side_effect=OpenAITranscriptionError("Invalid OpenAI API key; check OPENAI_API_KEY")
    )
    sessions = MagicMock()
    session = MagicMock()
    session.id = uuid4()
    session.started_at = MagicMock()
    sessions.create.return_value = session

    svc = VideoImportService(
        settings=Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}"),
        sessions=sessions,
        transcripts=MagicMock(),
        transcriber=transcriber,
    )

    def _resolve(*_a, **_k):
        return video

    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.resolve_media_source",
        _resolve,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.probe_media_duration_seconds",
        lambda _p: 30.0,
    )

    def _extract(**kwargs):
        dest = kwargs["dest_wav"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write_silent_wav(dest, seconds=30.0)

    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.extract_audio_to_wav",
        _extract,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.write_source_media_manifest",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        "live_meeting_transcriber.application.video_import_service.append_timeline_entry",
        lambda *_a, **_k: None,
    )

    from datetime import UTC, datetime

    from live_meeting_transcriber.application.video_import_service import VideoImportError

    session.started_at = datetime.now(tz=UTC)

    with pytest.raises(VideoImportError, match="No transcript segments"):
        await svc.import_video(source=str(video), extract_slides=False)


def test_mean_absolute_difference() -> None:
    assert mean_absolute_difference(b"\x00\x00", b"\x00\x00") == 0.0
    assert mean_absolute_difference(b"\x00", b"\xff") == 255.0
