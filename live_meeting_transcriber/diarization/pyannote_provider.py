"""Optional pyannote.audio diarization (lazy import — not required for core installs)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from live_meeting_transcriber.diarization.labels import normalize_pyannote_speaker_label
from live_meeting_transcriber.domain.models import AudioChunk, DiarizationSegment


class PyannoteDiarizationProvider:
    """Runs a pretrained pyannote pipeline on each chunk WAV (blocking work in a thread)."""

    def __init__(self, *, hf_token: str, model_id: str) -> None:
        self._hf_token = hf_token
        self._model_id = model_id
        self._pipeline: object | None = None

    def _ensure_pipeline(self) -> object:
        if self._pipeline is not None:
            return self._pipeline
        try:
            from pyannote.audio import Pipeline
        except ImportError as e:
            raise RuntimeError(
                "pyannote.audio is not installed. Install optional extras: "
                "uv pip install 'live-meeting-transcriber[diarization]'"
            ) from e
        try:
            pipeline = Pipeline.from_pretrained(self._model_id, token=self._hf_token)
        except TypeError:
            pipeline = Pipeline.from_pretrained(self._model_id, use_auth_token=self._hf_token)
        self._pipeline = pipeline
        return pipeline

    def _run_sync(self, chunk: AudioChunk) -> list[DiarizationSegment]:
        pipeline = self._ensure_pipeline()
        raw = pipeline(str(chunk.path))
        # pyannote.audio 3.x returns DiarizeOutput; older pipelines return Annotation directly.
        annotation = getattr(raw, "speaker_diarization", raw)
        out: list[DiarizationSegment] = []
        for turn, _track, speaker in annotation.itertracks(yield_label=True):
            t0 = chunk.started_at + timedelta(seconds=float(turn.start))
            t1 = chunk.started_at + timedelta(seconds=float(turn.end))
            key = normalize_pyannote_speaker_label(str(speaker))
            out.append(
                DiarizationSegment(
                    started_at=t0,
                    ended_at=t1,
                    speaker_key=key,
                    chunk_id=chunk.id,
                )
            )
        return out

    async def diarize_chunk(self, *, chunk: AudioChunk) -> list[DiarizationSegment]:
        return await asyncio.to_thread(self._run_sync, chunk)
