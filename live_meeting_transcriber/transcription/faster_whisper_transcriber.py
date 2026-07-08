from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

from live_meeting_transcriber.domain.exceptions import (
    EmptyTranscriptionError,
    TranscriptionProviderError,
)
from live_meeting_transcriber.domain.models import AudioChunk, ProviderMetadata, TranscriptSegment


class FasterWhisperTranscriptionError(TranscriptionProviderError):
    """faster-whisper-specific transcription failure. Recoverable by default: the application
    layer catches the domain base type and skips the chunk without importing this class."""


class FasterWhisperTranscriptionProvider:
    """Local speech-to-text via faster-whisper (CTranslate2). Lazy-loads the model on first use."""

    def __init__(
        self,
        *,
        model_size: str,
        device: str,
        compute_type: str,
        language: str | None,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper is not installed. Install with: uv sync --extra faster-whisper"
            ) from e
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        return self._model

    async def warm_up(self) -> None:
        """Load (and download, if needed) the model once, off the event loop.

        Called before the recording loop so the first chunk isn't slow and any
        download/load failure surfaces once up front instead of being retried and
        silently swallowed on every chunk.
        """
        try:
            await asyncio.to_thread(self._ensure_model)
        except RuntimeError:
            raise
        except Exception as e:
            raise FasterWhisperTranscriptionError(str(e)) from e

    def _transcribe_sync(self, chunk: AudioChunk) -> TranscriptSegment:
        try:
            model = self._ensure_model()
            segments_gen, info = model.transcribe(
                str(chunk.path),
                language=self._language,
                beam_size=5,
                vad_filter=True,
            )
            parts: list[str] = []
            for seg in segments_gen:
                t = seg.text.strip()
                if t:
                    parts.append(t)
            text = " ".join(parts).strip()
        except RuntimeError:
            raise
        except Exception as e:
            raise FasterWhisperTranscriptionError(str(e)) from e

        if not text:
            raise EmptyTranscriptionError("faster-whisper returned empty text")

        lang = getattr(info, "language", None)
        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text=text,
            metadata=ProviderMetadata(
                provider="faster_whisper",
                model=self._model_size,
                extra={"language": lang} if lang else {},
            ),
        )

    def _transcribe_path_segments_sync(self, path: Path) -> list[tuple[float, float, str]]:
        model = self._ensure_model()
        segments_gen, _info = model.transcribe(
            str(path),
            language=self._language,
            beam_size=5,
            vad_filter=True,
        )
        out: list[tuple[float, float, str]] = []
        for seg in segments_gen:
            t = seg.text.strip()
            if t:
                out.append((float(seg.start), float(seg.end), t))
        return out

    def _transcribe_stereo_sync(
        self, chunk: AudioChunk, mic_path: Path, sys_path: Path
    ) -> list[TranscriptSegment]:
        mic_parts = self._transcribe_path_segments_sync(mic_path)
        sys_parts = self._transcribe_path_segments_sync(sys_path)
        lang_meta: dict[str, str] = {}
        rows: list[TranscriptSegment] = []
        for t0, t1, text in mic_parts:
            rows.append(
                TranscriptSegment(
                    session_id=chunk.session_id,
                    chunk_id=chunk.id,
                    started_at=chunk.started_at + timedelta(seconds=t0),
                    ended_at=chunk.started_at + timedelta(seconds=t1),
                    text=text,
                    speaker="YOU",
                    metadata=ProviderMetadata(
                        provider="faster_whisper",
                        model=self._model_size,
                        extra=dict(lang_meta),
                    ),
                )
            )
        for t0, t1, text in sys_parts:
            rows.append(
                TranscriptSegment(
                    session_id=chunk.session_id,
                    chunk_id=chunk.id,
                    started_at=chunk.started_at + timedelta(seconds=t0),
                    ended_at=chunk.started_at + timedelta(seconds=t1),
                    text=text,
                    speaker="REMOTE",
                    metadata=ProviderMetadata(
                        provider="faster_whisper",
                        model=self._model_size,
                        extra=dict(lang_meta),
                    ),
                )
            )
        rows.sort(key=lambda s: s.started_at)
        return rows

    async def transcribe_stereo_chunk(
        self, *, chunk: AudioChunk, mic_path: Path, sys_path: Path
    ) -> list[TranscriptSegment]:
        return await asyncio.to_thread(self._transcribe_stereo_sync, chunk, mic_path, sys_path)

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        return await asyncio.to_thread(self._transcribe_sync, chunk)
