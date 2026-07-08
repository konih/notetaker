from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.domain.exceptions import TranscriptionProviderError
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment


def _make_chunk(tmp_path: Path, session_id: object) -> AudioChunk:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    path = tmp_path / "chunk.wav"
    path.write_bytes(b"RIFF")
    return AudioChunk(
        session_id=session_id,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        path=path,
        sample_rate_hz=16000,
        channels=1,
    )


def _make_recorder(tmp_path: Path, transcriber: object) -> tuple[Recorder, MagicMock]:
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    transcripts = MagicMock()
    recorder = Recorder(
        audio=MagicMock(),
        transcriber=transcriber,
        transcripts=transcripts,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="openai",
    )
    return recorder, transcripts


@pytest.mark.asyncio
async def test_recoverable_provider_error_is_skipped_and_recording_continues(
    tmp_path: Path,
) -> None:
    """A recoverable domain TranscriptionProviderError is swallowed: the chunk is skipped
    (TranscriptionChunkFailed emitted, no segment persisted) and the caller can keep going.

    The test depends only on the domain error type — no import from ``transcription/`` concretes.
    """
    sid = uuid4()

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            raise TranscriptionProviderError("temporary rate limit", recoverable=True)

    recorder, transcripts = _make_recorder(tmp_path, _Transcriber())
    events: list[str] = []
    audio_root = tmp_path / "audio"
    audio_root.mkdir()

    # Must NOT raise — recoverable failures are logged and skipped.
    await recorder._ingest_captured_chunk(
        session_id=sid,
        chunk=_make_chunk(tmp_path, sid),
        session_audio_root=audio_root,
        sample_rate_hz=16000,
        on_application_event=lambda ev: events.append(type(ev).__name__),
        on_segment=None,
    )

    assert transcripts.append.call_count == 0
    assert "TranscriptionChunkFailed" in events


@pytest.mark.asyncio
async def test_non_recoverable_provider_error_propagates(tmp_path: Path) -> None:
    """A non-recoverable domain TranscriptionProviderError propagates out of the chunk
    handler instead of being silently skipped."""
    sid = uuid4()

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            raise TranscriptionProviderError("fatal provider misconfiguration", recoverable=False)

    recorder, transcripts = _make_recorder(tmp_path, _Transcriber())
    audio_root = tmp_path / "audio"
    audio_root.mkdir()

    with pytest.raises(TranscriptionProviderError):
        await recorder._ingest_captured_chunk(
            session_id=sid,
            chunk=_make_chunk(tmp_path, sid),
            session_audio_root=audio_root,
            sample_rate_hz=16000,
            on_application_event=None,
            on_segment=None,
        )

    assert transcripts.append.call_count == 0
