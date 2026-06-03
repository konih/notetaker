from __future__ import annotations

from openai import AsyncOpenAI

from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import AudioChunk, ProviderMetadata, TranscriptSegment


class OpenAITranscriptionError(RuntimeError):
    pass


def _openai_error_message(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    body = str(exc).lower()
    if status == 429 or "rate_limit" in body:
        return "OpenAI rate limit reached; wait and retry or use smaller chunks"
    if status == 401 or "invalid_api_key" in body or "incorrect api key" in body:
        return "Invalid OpenAI API key; check OPENAI_API_KEY"
    if status == 413 or "too large" in body:
        return "Audio chunk too large for OpenAI transcription"
    if status == 400 and ("corrupt" in body or "invalid" in body or "format" in body):
        return f"OpenAI rejected audio chunk (corrupt or unsupported format): {exc}"
    return f"OpenAI transcription failed: {exc}"


class OpenAITranscriptionProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment:
        if not chunk.path.is_file():
            raise OpenAITranscriptionError(f"Audio chunk file missing: {chunk.path}")

        try:
            with chunk.path.open("rb") as f:
                resp = await self._client.audio.transcriptions.create(
                    model=self._model,
                    file=f,
                )
        except Exception as e:
            raise OpenAITranscriptionError(_openai_error_message(e)) from e

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
