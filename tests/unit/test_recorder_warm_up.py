from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.audio.session_recording import FfmpegSessionAudioStore
from live_meeting_transcriber.audio.wav_ops import FfmpegWavOps
from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from live_meeting_transcriber.domain.ports import AudioCapture
from live_meeting_transcriber.transcription.faster_whisper_transcriber import (
    FasterWhisperTranscriptionError,
)


def _make_audio(sid: UUID, tmp_path: Path, calls: list[str]) -> AudioCapture:
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

    return _Audio()


@pytest.mark.asyncio
async def test_warm_up_failure_keeps_recording_but_skips_transcription(tmp_path: Path) -> None:
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    calls: list[str] = []
    captured_two = asyncio.Event()

    class _Transcriber:
        transcribe_calls = 0

        async def warm_up(self) -> None:
            raise FasterWhisperTranscriptionError("bad value(s) in fds_to_keep")

        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            _Transcriber.transcribe_calls += 1
            raise AssertionError("transcribe must not be called when warm-up failed")

    def _on_audio(_: str) -> None:
        if len(calls) >= 2:
            captured_two.set()

    events: list[object] = []
    transcripts = MagicMock()
    recorder = Recorder(
        session_audio=FfmpegSessionAudioStore(),
        wav_ops=FfmpegWavOps(),
        audio=_make_audio(sid, tmp_path, calls),
        transcriber=_Transcriber(),
        transcripts=transcripts,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="faster_whisper",
    )

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_application_event=lambda e: (events.append(e), _on_audio("x"))[-1],  # type: ignore[func-returns-value]
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(captured_two.wait(), timeout=2.0)
    task.cancel()
    await task

    # Recording kept capturing chunks...
    assert calls == ["cap", "cap"] or calls[:2] == ["cap", "cap"]
    # ...transcription was never attempted...
    assert _Transcriber.transcribe_calls == 0
    assert transcripts.append.call_count == 0
    # ...and a single user-facing "unavailable" event was emitted.
    unavailable = [e for e in events if isinstance(e, ev.TranscriptionUnavailable)]
    assert len(unavailable) == 1
    assert "fds_to_keep" in unavailable[0].message
    # No per-chunk "started" events since transcription is disabled.
    assert not any(isinstance(e, ev.TranscriptionChunkStarted) for e in events)


@pytest.mark.asyncio
async def test_warm_up_success_allows_transcription(tmp_path: Path) -> None:
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    calls: list[str] = []
    warmed = {"n": 0}
    first_started = asyncio.Event()

    class _Transcriber:
        async def warm_up(self) -> None:
            warmed["n"] += 1

        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError

            raise EmptyTranscriptionError("empty")

    events: list[object] = []

    def _sink(e: object) -> None:
        events.append(e)
        if isinstance(e, ev.TranscriptionChunkStarted):
            first_started.set()

    recorder = Recorder(
        session_audio=FfmpegSessionAudioStore(),
        wav_ops=FfmpegWavOps(),
        audio=_make_audio(sid, tmp_path, calls),
        transcriber=_Transcriber(),
        transcripts=MagicMock(),
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="faster_whisper",
    )

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_application_event=_sink,
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(first_started.wait(), timeout=2.0)
    task.cancel()
    await task

    assert warmed["n"] == 1
    assert any(isinstance(e, ev.TranscriptionChunkStarted) for e in events)
    assert not any(isinstance(e, ev.TranscriptionUnavailable) for e in events)
