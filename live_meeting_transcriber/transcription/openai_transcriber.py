from __future__ import annotations

from openai import AsyncOpenAI

from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import AudioChunk, ProviderMetadata, TranscriptSegment


class OpenAITranscriptionError(RuntimeError):
    pass


class OpenAITranscriptionProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        try:
            with chunk.path.open("rb") as f:
                resp = await self._client.audio.transcriptions.create(
                    model=self._model,
                    file=f,
                )
        except Exception as e:
            raise OpenAITranscriptionError(str(e)) from e

        text = getattr(resp, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise EmptyTranscriptionError("OpenAI transcription returned empty text")

        return TranscriptSegment(
            session_id=chunk.session_id,
            chunk_id=chunk.id,
            started_at=chunk.started_at,
            ended_at=chunk.ended_at,
            text=text.strip(),
            metadata=ProviderMetadata(provider="openai", model=self._model, extra={}),
        )
