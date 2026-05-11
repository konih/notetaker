from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment


@pytest.mark.asyncio
async def test_recorder_skips_empty_transcription_and_continues(tmp_path: Path) -> None:
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()

    calls: list[str] = []
    first_segment_saved = asyncio.Event()

    class _Audio:
        def capture_chunk(self, **_kwargs: object) -> AudioChunk:
            n = len(calls)
            t0 = datetime(2026, 1, 1, 12, 0, 0)
            path = tmp_path / f"c{n}.wav"
            path.write_bytes(b"RIFF")
            calls.append("cap")
            return AudioChunk(
                session_id=sid,
                started_at=t0,
                ended_at=t0 + timedelta(seconds=1),
                path=path,
                sample_rate_hz=16000,
                channels=1,
            )

    class _Transcriber:
        def __init__(self) -> None:
            self._n = 0

        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            self._n += 1
            if self._n == 1:
                raise EmptyTranscriptionError("empty")
            t0 = chunk.started_at
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=t0,
                ended_at=t0 + timedelta(seconds=1),
                text="hello",
            )

    transcripts = MagicMock()
    diar_repo = MagicMock()
    recorder = Recorder(
        audio=_Audio(),
        transcriber=_Transcriber(),
        diarizer=AsyncMock(return_value=[]),
        transcripts=transcripts,
        diarization_segments=diar_repo,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        diarization_enabled=False,
    )

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_segment=lambda _s: first_segment_saved.set(),
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(first_segment_saved.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == ["cap", "cap"]
    assert transcripts.append.call_count == 1
