from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from live_meeting_transcriber.domain.models import (
    AudioChunk,
    MeetingSession,
    Summary,
    TranscriptSegment,
)


class AudioSource(Protocol):
    name: str
    description: str


@runtime_checkable
class AudioDeviceProvider(Protocol):
    def list_sources(self) -> list[AudioSource]: ...

    def get_default_monitor_source(self) -> str | None: ...


@runtime_checkable
class AudioCapture(Protocol):
    def capture_chunk(
        self,
        *,
        session_id: UUID,
        source: str,
        chunk_seconds: int,
        sample_rate_hz: int,
        channels: int,
        output_dir: Path,
    ) -> AudioChunk: ...


@runtime_checkable
class TranscriptionProvider(Protocol):
    async def transcribe(self, *, chunk: AudioChunk) -> TranscriptSegment: ...


@runtime_checkable
class DiarizationProvider(Protocol):
    async def diarize(self, *, segment: TranscriptSegment) -> TranscriptSegment: ...


@runtime_checkable
class SummarizationProvider(Protocol):
    async def summarize(self, *, session: MeetingSession, segments: Iterable[TranscriptSegment]) -> Summary: ...


@runtime_checkable
class MeetingSessionRepository(Protocol):
    def create(self, session: MeetingSession) -> MeetingSession: ...

    def get(self, session_id: UUID) -> MeetingSession | None: ...

    def list(self) -> list[MeetingSession]: ...

    def end(self, session_id: UUID) -> None: ...

    def update_title(self, session_id: UUID, title: str) -> MeetingSession | None: ...


@runtime_checkable
class TranscriptRepository(Protocol):
    def append(self, segment: TranscriptSegment) -> TranscriptSegment: ...

    def list_by_session(self, session_id: UUID) -> list[TranscriptSegment]: ...


@runtime_checkable
class SummaryRepository(Protocol):
    def upsert(self, summary: Summary) -> Summary: ...

    def get_by_session(self, session_id: UUID) -> Summary | None: ...
