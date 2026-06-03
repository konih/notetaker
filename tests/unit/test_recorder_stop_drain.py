from __future__ import annotations

import asyncio
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment


def _write_silent_wav(path: Path, *, seconds: float = 2.0, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * nframes)


@pytest.mark.asyncio
async def test_stop_drains_inflight_transcription(tmp_path: Path) -> None:
    """Cancel during transcribe must still finish the in-flight chunk."""
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    transcribe_started = asyncio.Event()
    finish_transcription = asyncio.Event()

    class _Audio:
        def capture_chunk(self, **_kwargs: object) -> AudioChunk:
            p = tmp_path / f"{uuid4().hex}.wav"
            _write_silent_wav(p, seconds=2.0)
            return AudioChunk(
                session_id=sid,
                started_at=t0,
                ended_at=t0 + timedelta(seconds=2),
                path=p,
                sample_rate_hz=16000,
                channels=1,
            )

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            transcribe_started.set()
            await finish_transcription.wait()
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=chunk.started_at,
                ended_at=chunk.ended_at,
                text="after_drain",
            )

    transcripts = MagicMock()
    recorder = Recorder(
        audio=_Audio(),
        transcriber=_Transcriber(),
        transcripts=transcripts,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="openai",
    )

    run_task = asyncio.create_task(
        recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=2,
            sample_rate_hz=16000,
            channels=1,
        )
    )
    await asyncio.wait_for(transcribe_started.wait(), timeout=2.0)
    run_task.cancel()
    finish_transcription.set()
    await run_task

    assert transcripts.append.call_count == 1
    saved = transcripts.append.call_args[0][0]
    assert saved.text == "after_drain"
    assert saved.speaker == "unknown"
