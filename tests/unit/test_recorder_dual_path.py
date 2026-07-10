"""Characterization of the recorder's dual-path (stereo) transcription branch.

This branch (``AUDIO_STEREO_MODE=dual_path`` + a stereo-capable ``faster_whisper``
transcriber on a 2-channel chunk) is the one that *preserves* per-segment speaker
labels and emits ``DiarizationChunkCompleted`` with the real detected speakers —
diverging from the mixdown branch, which forces ``speaker="unknown"`` and emits an
empty detected-speaker set. It was previously uncovered; these tests lock the
observable behavior before the A4 decomposition refactors the branch out.

Hermetic: ``extract_mono_channel_wav`` (ffmpeg) is patched so the test needs no
ffmpeg binary; the first chunk's full-session append uses ``shutil.copy2`` (no
ffmpeg), so no other subprocess is spawned.
"""

from __future__ import annotations

import asyncio
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from live_meeting_transcriber.application import recorder as recorder_module
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    DiarizationChunkCompleted,
    TranscriptionChunkCompleted,
    TranscriptionChunkEmpty,
    TranscriptionChunkFailed,
    TranscriptSegmentPersisted,
)
from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment


def _write_silent_wav(
    path: Path, *, seconds: float = 2.0, rate: int = 16000, channels: int = 2
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * nframes * channels)


async def _run_one_stereo_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    segments: list[TranscriptSegment] | Exception,
) -> tuple[MagicMock, list[ApplicationEvent]]:
    """Drive ``record_forever`` for a single stereo chunk, then cancel.

    Returns the transcripts repo mock and the captured application-event list.
    ``segments`` may be a list (returned by ``transcribe_stereo_chunk``) or an
    Exception instance to raise.
    """
    sid = uuid4()
    chunk_dir = tmp_path / "chunks"
    t0 = datetime(2026, 1, 1, 12, 0, 0)

    # Avoid ffmpeg: return real (empty) temp files for the split mono channels.
    def _fake_extract(source: Path, channel: int, *, sample_rate_hz: int) -> Path:
        p = tmp_path / f"mono_{channel}_{uuid4().hex}.wav"
        _write_silent_wav(p, seconds=2.0, channels=1)
        return p

    monkeypatch.setattr(recorder_module, "extract_mono_channel_wav", _fake_extract)

    class _Audio:
        def capture_chunk(self, **_kwargs: object) -> AudioChunk:
            p = tmp_path / f"{uuid4().hex}.wav"
            _write_silent_wav(p, seconds=2.0, channels=2)
            return AudioChunk(
                session_id=sid,
                started_at=t0,
                ended_at=t0 + timedelta(seconds=2),
                path=p,
                sample_rate_hz=16000,
                channels=2,
            )

    class _StereoTranscriber:
        async def transcribe_stereo_chunk(
            self, *, chunk: AudioChunk, mic_path: Path, sys_path: Path
        ) -> list[TranscriptSegment]:
            if isinstance(segments, Exception):
                raise segments
            return segments

        async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:  # pragma: no cover
            raise AssertionError("mixdown path must not be taken for a dual_path stereo chunk")

    transcripts = MagicMock()
    recorder = Recorder(
        audio=_Audio(),
        transcriber=_StereoTranscriber(),
        transcripts=transcripts,
        keep_audio_chunks=False,
        chunk_output_dir=chunk_dir,
        data_dir=tmp_path,
        audio_stereo_mode="dual_path",
        transcription_provider="faster_whisper",
    )

    events: list[ApplicationEvent] = []
    done = asyncio.Event()

    def _on_event(e: ApplicationEvent) -> None:
        events.append(e)
        # Signal once the chunk has been fully processed (completed or skipped).
        if isinstance(
            e,
            (DiarizationChunkCompleted, TranscriptionChunkEmpty, TranscriptionChunkFailed),
        ):
            done.set()

    def _on_seg(_s: TranscriptSegment) -> None:
        pass

    async def _run() -> None:
        await recorder.record_forever(
            session_id=sid,
            source="sink.monitor",
            chunk_seconds=2,
            sample_rate_hz=16000,
            channels=2,
            on_segment=_on_seg,
            on_application_event=_on_event,
        )

    task = asyncio.create_task(_run())
    try:
        await asyncio.wait_for(done.wait(), timeout=5.0)
    finally:
        task.cancel()
        await task
    return transcripts, events


@pytest.mark.asyncio
async def test_dual_path_preserves_segment_speakers_and_detects_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = uuid4()
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    seg_you = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        text="hi there",
        speaker="YOU",
    )
    seg_remote = TranscriptSegment(
        session_id=sid,
        started_at=t0 + timedelta(seconds=1),
        ended_at=t0 + timedelta(seconds=2),
        text="hello back",
        speaker="REMOTE",
    )

    transcripts, events = await _run_one_stereo_chunk(
        tmp_path, monkeypatch, segments=[seg_you, seg_remote]
    )

    # Both segments persisted, speakers NOT forced to "unknown".
    assert transcripts.append.call_count == 2
    saved = [c.args[0].speaker for c in transcripts.append.call_args_list]
    assert saved == ["YOU", "REMOTE"]

    # DiarizationChunkCompleted carries the real detected speakers.
    diar = [e for e in events if isinstance(e, DiarizationChunkCompleted)]
    assert len(diar) == 1
    assert diar[0].detected_speakers == frozenset({"YOU", "REMOTE"})

    # Ordering: dual path persists all segments BEFORE emitting completed/diarization.
    kinds = [
        type(e).__name__
        for e in events
        if isinstance(
            e,
            (TranscriptSegmentPersisted, TranscriptionChunkCompleted, DiarizationChunkCompleted),
        )
    ]
    assert kinds == [
        "TranscriptSegmentPersisted",
        "TranscriptSegmentPersisted",
        "TranscriptionChunkCompleted",
        "DiarizationChunkCompleted",
    ]


@pytest.mark.asyncio
async def test_dual_path_empty_segments_skips_without_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcripts, events = await _run_one_stereo_chunk(tmp_path, monkeypatch, segments=[])

    assert transcripts.append.call_count == 0
    assert any(type(e).__name__ == "TranscriptionChunkEmpty" for e in events)
    assert not any(isinstance(e, DiarizationChunkCompleted) for e in events)
