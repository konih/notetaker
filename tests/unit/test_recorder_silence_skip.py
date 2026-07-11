"""F1: the recorder must not send silent chunks to the transcriber.

The chunk's audio is still appended to ``full_session.wav`` first (finalize and
diarization need the complete session audio); only the live transcription call
is skipped, an ``AudioChunkSkippedSilent`` event is emitted, and the per-chunk
WAV follows the normal ``keep_audio_chunks`` cleanup policy.
"""

from __future__ import annotations

import asyncio
import math
import struct
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment
from tests.e2e.video_helpers import ffmpeg_available


def _write_wav(
    path: Path,
    samples: list[float],
    *,
    sample_rate_hz: int = 16000,
    channels: int = 1,
) -> Path:
    ints = [max(-32768, min(32767, round(s * 32767))) for s in samples]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(struct.pack(f"<{len(ints)}h", *ints))
    return path


def _loud_samples(n: int = 8000) -> list[float]:
    return [0.5 * math.sin(2 * math.pi * 220 * i / 16000) for i in range(n)]


def _chunk(sid: object, path: Path, *, channels: int = 1) -> AudioChunk:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    return AudioChunk(
        session_id=sid,  # type: ignore[arg-type]
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        path=path,
        sample_rate_hz=16000,
        channels=channels,
    )


def _recorder(tmp_path: Path, audio: object, transcriber: object, **overrides: object) -> Recorder:
    kwargs: dict[str, object] = dict(
        audio=audio,
        transcriber=transcriber,
        transcripts=MagicMock(),
        keep_audio_chunks=False,
        chunk_output_dir=tmp_path / "chunks",
        data_dir=tmp_path,
        audio_stereo_mode="mixdown",
        transcription_provider="faster_whisper",
    )
    kwargs.update(overrides)
    return Recorder(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_silent_chunk_is_not_transcribed_but_loud_chunk_is(tmp_path: Path) -> None:
    sid = uuid4()
    (tmp_path / "chunks").mkdir()

    captured: list[Path] = []

    class _Audio:
        def capture_chunk(self, **_kw: object) -> AudioChunk:
            n = len(captured)
            path = tmp_path / f"c{n}.wav"
            # First chunk digital silence, all later chunks loud speech-like audio.
            _write_wav(path, [0.0] * 8000 if n == 0 else _loud_samples())
            captured.append(path)
            return _chunk(sid, path)

    transcribed: list[Path] = []
    segment_saved = asyncio.Event()

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            transcribed.append(chunk.path)
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=chunk.started_at,
                ended_at=chunk.ended_at,
                text="hello",
            )

    events: list[object] = []
    recorder = _recorder(tmp_path, _Audio(), _Transcriber())

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_segment=lambda _s: segment_saved.set(),
            on_application_event=events.append,
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(segment_saved.wait(), timeout=5.0)
    task.cancel()
    await task

    # The silent chunk never reached the transcriber; the loud one did.
    assert len(transcribed) >= 1
    assert captured[0] not in transcribed

    skips = [e for e in events if isinstance(e, ev.AudioChunkSkippedSilent)]
    assert len(skips) >= 1
    assert skips[0].session_id == sid
    assert skips[0].rms_dbfs < -70.0

    # Skipped audio still landed in the full-session WAV (finalize needs it) …
    full = tmp_path / "sessions" / str(sid) / "full_session.wav"
    assert full.exists()
    with wave.open(str(full), "rb") as w:
        # The skipped silent chunk itself was persisted (first chunk: plain copy, no ffmpeg).
        assert w.getnframes() >= 8000
        if ffmpeg_available():
            # Later chunks are appended via ffmpeg concat; only assert the combined
            # length where the binary exists (the unit CI job has no ffmpeg).
            assert w.getnframes() >= 16000  # silent chunk (8000) + first loud chunk (8000)

    # … and the per-chunk WAV was cleaned up like any other processed chunk.
    assert not captured[0].exists()


@pytest.mark.asyncio
async def test_silent_chunk_transcribed_when_skip_disabled(tmp_path: Path) -> None:
    sid = uuid4()
    (tmp_path / "chunks").mkdir()

    class _Audio:
        def capture_chunk(self, **_kw: object) -> AudioChunk:
            path = tmp_path / f"c{uuid4().hex}.wav"
            _write_wav(path, [0.0] * 8000)
            return _chunk(sid, path)

    segment_saved = asyncio.Event()

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=chunk.started_at,
                ended_at=chunk.ended_at,
                text="…",
            )

    recorder = _recorder(tmp_path, _Audio(), _Transcriber(), silence_skip_enabled=False)

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_segment=lambda _s: segment_saved.set(),
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(segment_saved.wait(), timeout=5.0)
    task.cancel()
    await task
    # Reaching here means the silent chunk was transcribed (no skip).


@pytest.mark.asyncio
async def test_dual_path_silent_stereo_chunk_is_skipped(tmp_path: Path) -> None:
    sid = uuid4()
    (tmp_path / "chunks").mkdir()

    class _Audio:
        def capture_chunk(self, **_kw: object) -> AudioChunk:
            path = tmp_path / f"c{uuid4().hex}.wav"
            _write_wav(path, [0.0] * 16000, channels=2)
            return _chunk(sid, path, channels=2)

    stereo_calls: list[object] = []

    class _DualTranscriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            raise AssertionError("mono path must not run in dual_path mode")

        async def transcribe_stereo_chunk(self, **_kw: object) -> list[TranscriptSegment]:
            stereo_calls.append(_kw)
            return []

    events: list[object] = []
    skipped = asyncio.Event()

    def _on_event(e: object) -> None:
        events.append(e)
        if isinstance(e, ev.AudioChunkSkippedSilent):
            skipped.set()

    recorder = _recorder(tmp_path, _Audio(), _DualTranscriber(), audio_stereo_mode="dual_path")

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=2,
            on_application_event=_on_event,
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(skipped.wait(), timeout=5.0)
    task.cancel()
    await task

    assert stereo_calls == []


@pytest.mark.asyncio
async def test_unreadable_chunk_fails_open_and_is_transcribed(tmp_path: Path) -> None:
    """A chunk whose level cannot be measured must be transcribed, never skipped."""
    sid = uuid4()
    (tmp_path / "chunks").mkdir()

    class _Audio:
        def capture_chunk(self, **_kw: object) -> AudioChunk:
            path = tmp_path / f"c{uuid4().hex}.wav"
            path.write_bytes(b"RIFF")  # not a valid WAV
            return _chunk(sid, path)

    segment_saved = asyncio.Event()

    class _Transcriber:
        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
            return TranscriptSegment(
                session_id=sid,
                chunk_id=chunk.id,
                started_at=chunk.started_at,
                ended_at=chunk.ended_at,
                text="ok",
            )

    recorder = _recorder(tmp_path, _Audio(), _Transcriber())

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=1,
            sample_rate_hz=16000,
            channels=1,
            on_segment=lambda _s: segment_saved.set(),
        )

    task = asyncio.create_task(_run())
    await asyncio.wait_for(segment_saved.wait(), timeout=5.0)
    task.cancel()
    await task
