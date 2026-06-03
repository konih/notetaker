from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from live_meeting_transcriber.domain.models import (
    AudioChunk,
    DiarizationSegment,
    MeetingSession,
    SlideCandidate,
    SlideDetectionParams,
    SpeakerAlias,
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

    def get_default_microphone_source(self) -> str | None: ...


@runtime_checkable
class AudioCapture(Protocol):
    def capture_chunk(
        self,
        *,
        session_id: UUID,
        source: str,
        microphone_source: str | None = None,
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
    async def diarize_chunk(self, *, chunk: AudioChunk) -> list[DiarizationSegment]: ...


@runtime_checkable
class DiarizationRepository(Protocol):
    def replace_for_session(self, session_id: UUID, segments: list[DiarizationSegment]) -> None: ...

    def append_segments(self, session_id: UUID, segments: list[DiarizationSegment]) -> None: ...

    def list_by_session(self, session_id: UUID) -> list[DiarizationSegment]: ...

    def delete_for_session(self, session_id: UUID) -> None: ...


@runtime_checkable
class SpeakerAliasRepository(Protocol):
    def get_map(self, session_id: UUID) -> dict[str, str]: ...

    def set_alias(self, session_id: UUID, speaker_key: str, display_name: str) -> None: ...

    def list_aliases(self, session_id: UUID) -> list[SpeakerAlias]: ...


@runtime_checkable
class SummarizationProvider(Protocol):
    async def summarize(
        self,
        *,
        session: MeetingSession,
        segments: Iterable[TranscriptSegment],
        speaker_display: dict[str, str] | None = None,
        user_context: str | None = None,
    ) -> Summary: ...


@runtime_checkable
class MeetingSessionRepository(Protocol):
    def create(self, session: MeetingSession) -> MeetingSession: ...

    def get(self, session_id: UUID) -> MeetingSession | None: ...

    def list(self) -> list[MeetingSession]: ...

    def end(self, session_id: UUID) -> None: ...

    def reopen(self, session_id: UUID) -> MeetingSession | None:
        """Clear ``ended_at`` so the session can accept further recording."""
        ...

    def update_title(self, session_id: UUID, title: str) -> MeetingSession | None: ...

    def update_details(
        self,
        session_id: UUID,
        *,
        title: str | None = None,
        notes: str | None = None,
        attendees: list[str] | None = None,
    ) -> MeetingSession | None: ...

    def delete(self, session_id: UUID) -> bool:
        """Remove session and all transcript, summary, and speaker-name rows. Returns False if missing."""
        ...


@runtime_checkable
class TranscriptRepository(Protocol):
    def append(self, segment: TranscriptSegment) -> TranscriptSegment: ...

    def list_by_session(self, session_id: UUID) -> list[TranscriptSegment]: ...

    def replace_session_transcript(
        self, session_id: UUID, segments: list[TranscriptSegment]
    ) -> None:
        """Replace all transcript rows for a session (e.g. offline WhisperX pass)."""

    def update_segment_text(self, segment_id: UUID, text: str) -> TranscriptSegment | None: ...

    def update_segment_speaker(
        self, segment_id: UUID, speaker: str
    ) -> TranscriptSegment | None: ...


@runtime_checkable
class KnownPeopleRepository(Protocol):
    """People the user has named (for autocomplete). Obsidian sync can populate ``source`` later."""

    def list_for_autocomplete(self) -> list[str]: ...

    def search_prefix(self, prefix: str, *, limit: int = 25) -> list[str]: ...

    def touch(self, display_name: str) -> None: ...


@runtime_checkable
class SessionSpeakerNameRepository(SpeakerAliasRepository, Protocol):
    """Per-meeting display names for diarization keys (e.g. speaker_1 → Frederik)."""

    def replace_map(self, session_id: UUID, mapping: dict[str, str]) -> None: ...


@runtime_checkable
class SummaryRepository(Protocol):
    def upsert(self, summary: Summary) -> Summary: ...

    def get_by_session(self, session_id: UUID) -> Summary | None: ...


@runtime_checkable
class SlideDetectionStrategy(Protocol):
    """Adapter for detecting presentation slide transitions in a video file."""

    def detect(
        self,
        *,
        video_path: Path,
        duration_seconds: float,
        params: SlideDetectionParams,
        preview_dir: Path | None = None,
    ) -> list[SlideCandidate]: ...
