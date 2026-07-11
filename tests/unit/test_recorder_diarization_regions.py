from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.audio.session_recording import FfmpegSessionAudioStore
from live_meeting_transcriber.audio.wav_ops import FfmpegWavOps
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment

from tests.unit.conftest import write_silent_wav


@pytest.mark.asyncio
async def test_recorder_live_chunk_sets_unknown_speaker_without_diarization(tmp_path: Path) -> None:
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    t0 = datetime(2026, 1, 1, 12, 0, 0)

    class _Audio:
        def capture_chunk(self, **_kwargs: object) -> AudioChunk:
            p = tmp_path / f"{uuid4().hex}.wav"
            write_silent_wav(p, seconds=2.0)
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
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=chunk.started_at,
                ended_at=chunk.ended_at,
                text="hello",
                speaker="should_be_overridden",
            )

    transcripts = MagicMock()
    recorder = Recorder(
        session_audio=FfmpegSessionAudioStore(),
        wav_ops=FfmpegWavOps(),
        audio=_Audio(),
        transcriber=_Transcriber(),
        transcripts=transcripts,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="openai",
        # These tests use digital-silence WAVs as stand-ins for speech; disable
        # the F1 silence skip so the chunks still reach the transcriber.
        silence_skip_enabled=False,
    )

    done = asyncio.Event()
    _seen: list[TranscriptSegment] = []

    def _on_seg(s: TranscriptSegment) -> None:
        _seen.append(s)
        done.set()

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=2,
            sample_rate_hz=16000,
            channels=1,
            on_segment=_on_seg,
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(done.wait(), timeout=5.0)
    task.cancel()
    await task

    assert transcripts.append.call_count == 1
    saved = transcripts.append.call_args[0][0]
    assert saved.speaker == "unknown"
    assert saved.text == "hello"
