"""Characterization of the OpenAI transcription adapter (T2, provider adapters).

Covers the pure error-mapping helper and the transcribe() outcomes (missing file,
empty result, success, API error -> domain error). Hermetic: no network — the OpenAI
client is stubbed. Construction only stores the API key, so no key is validated.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain.exceptions import EmptyTranscriptionError
from live_meeting_transcriber.domain.models import AudioChunk
from live_meeting_transcriber.transcription.openai_transcriber import (
    OpenAITranscriptionError,
    OpenAITranscriptionProvider,
    _openai_error_message,
)

from tests.unit.conftest import write_silent_wav


class _ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (_ApiError("boom", status_code=429), "rate limit"),
        (_ApiError("rate_limit exceeded"), "rate limit"),
        (_ApiError("nope", status_code=401), "Invalid OpenAI API key"),
        (_ApiError("incorrect api key provided"), "Invalid OpenAI API key"),
        (_ApiError("too big", status_code=413), "too large"),
        (_ApiError("file too large"), "too large"),
        (_ApiError("invalid format", status_code=400), "corrupt or unsupported"),
        (_ApiError("bad", status_code=400), "OpenAI transcription failed"),  # 400 w/o keyword
        (_ApiError("mystery failure"), "OpenAI transcription failed"),
    ],
)
def test_openai_error_message_maps_known_failures(exc: Exception, needle: str) -> None:
    assert needle in _openai_error_message(exc)


def _chunk(tmp_path: Path, *, exists: bool = True) -> AudioChunk:
    p = tmp_path / f"{uuid4().hex}.wav"
    if exists:
        write_silent_wav(p, seconds=1.0)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    return AudioChunk(
        session_id=uuid4(),
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        path=p,
        sample_rate_hz=16000,
        channels=1,
    )


def _provider_with_response(resp: object) -> OpenAITranscriptionProvider:
    prov = OpenAITranscriptionProvider(api_key="test-key", model="whisper-1")

    async def _create(**_kwargs: object) -> object:
        if isinstance(resp, Exception):
            raise resp
        return resp

    prov._client = SimpleNamespace(  # type: ignore[assignment]
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=_create))
    )
    return prov


@pytest.mark.asyncio
async def test_transcribe_missing_file_raises_before_any_call(tmp_path: Path) -> None:
    prov = _provider_with_response(SimpleNamespace(text="never used"))
    with pytest.raises(OpenAITranscriptionError, match="missing"):
        await prov.transcribe(chunk=_chunk(tmp_path, exists=False))


@pytest.mark.asyncio
async def test_transcribe_success_returns_segment(tmp_path: Path) -> None:
    prov = _provider_with_response(SimpleNamespace(text="  hello world  "))
    chunk = _chunk(tmp_path)
    seg = await prov.transcribe(chunk=chunk)
    assert seg.text == "hello world"
    assert seg.chunk_id == chunk.id
    assert seg.metadata is not None
    assert seg.metadata.provider == "openai"
    assert seg.metadata.model == "whisper-1"


@pytest.mark.asyncio
async def test_transcribe_empty_text_raises_empty(tmp_path: Path) -> None:
    prov = _provider_with_response(SimpleNamespace(text="   "))
    with pytest.raises(EmptyTranscriptionError):
        await prov.transcribe(chunk=_chunk(tmp_path))


@pytest.mark.asyncio
async def test_transcribe_api_error_becomes_domain_error(tmp_path: Path) -> None:
    prov = _provider_with_response(_ApiError("nope", status_code=401))
    with pytest.raises(OpenAITranscriptionError, match="Invalid OpenAI API key"):
        await prov.transcribe(chunk=_chunk(tmp_path))
