from __future__ import annotations

import builtins
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
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
from live_meeting_transcriber.domain.session_audio import AudioTimelineEntry


class AudioSource(Protocol):
    # Read-only members so frozen dataclasses (e.g. PactlAudioSource) satisfy the protocol.
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...


@runtime_checkable
class AudioDeviceProvider(Protocol):
    def list_sources(self) -> Sequence[AudioSource]: ...

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
        attendees: builtins.list[str] | None = None,
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


@runtime_checkable
class SessionAudioStore(Protocol):
    """Persistence of the rolling ``full_session.wav`` + wall-clock timeline (A9/A4).

    The path layout lives in :mod:`live_meeting_transcriber.domain.session_audio`;
    this port owns the file IO (ffmpeg concat, JSONL timeline read/write).
    """

    def append_chunk_with_timeline(
        self,
        *,
        session_audio_root: Path,
        chunk_wav: Path,
        sample_rate_hz: int,
        wall_started_at: datetime,
        wall_ended_at: datetime,
        fallback_duration_seconds: float,
        log: Any,
    ) -> None: ...

    def append_timeline_entry(
        self, session_audio_root: Path, entry: AudioTimelineEntry
    ) -> None: ...

    def load_timeline(self, session_audio_root: Path) -> list[AudioTimelineEntry]: ...


@runtime_checkable
class WavAudioOps(Protocol):
    """Local WAV inspection and transformation used by application services (A9/A4).

    Implementations may raise :class:`~live_meeting_transcriber.domain.exceptions.WavSegmentExtractionError`
    from :meth:`extract_time_range`.
    """

    def peak_linear(self, path: Path) -> float:
        """Peak absolute sample normalized to 0..1; 0.0 for empty/unsupported files."""
        ...

    def rms_dbfs(self, path: Path) -> float:
        """Overall RMS level in dBFS (<= 0.0); ``-inf`` for digital silence."""
        ...

    def duration_seconds(self, path: Path) -> float:
        """WAV duration in seconds; 0.0 on missing or corrupt files."""
        ...

    def is_transcribable(self, path: Path) -> bool:
        """Whether the file looks like non-empty audio worth sending to STT."""
        ...

    def mixdown_to_mono(self, path: Path, *, sample_rate_hz: int) -> Path:
        """Average a stereo WAV down to a temporary mono WAV; returns the temp path."""
        ...

    def extract_mono_channel(self, path: Path, channel: int, *, sample_rate_hz: int) -> Path:
        """Extract one channel (0 = left/mic, 1 = right/system) to a temp mono WAV."""
        ...

    def extract_time_range(
        self,
        *,
        src: Path,
        dest: Path,
        start_seconds: float,
        end_seconds: float,
        sample_rate_hz: int,
        channels: int,
    ) -> None:
        """Write ``dest`` as PCM WAV containing ``[start_seconds, end_seconds)`` of ``src``."""
        ...


@runtime_checkable
class MediaImporter(Protocol):
    """Resolve/download a video source and demux/probe its audio (A9).

    Implementations raise the domain errors ``MediaSourceError`` / ``MediaImportError``.
    """

    def resolve_source(self, *, source: str, download_dir: Path) -> Path: ...

    def title_from_source(self, source: str, video_path: Path) -> str: ...

    def probe_duration_seconds(self, path: Path) -> float: ...

    def extract_audio_to_wav(
        self, *, video_path: Path, dest_wav: Path, sample_rate_hz: int, channels: int
    ) -> Path: ...


@runtime_checkable
class SlideDetectionTools(Protocol):
    """Build slide-detection strategies and extract single video frames (A9).

    Implementations raise the domain error ``SlideDetectionError`` and may fall back
    to their wiring-time settings when ``name`` is ``None``.
    """

    def build_strategy(self, name: str | None = None) -> SlideDetectionStrategy: ...

    def extract_frame(
        self, *, video_path: Path, timestamp_seconds: float, dest_png: Path
    ) -> Path: ...


@runtime_checkable
class OfflineTranscriber(Protocol):
    """Full-session offline ASR (+ optional diarization) over ``full_session.wav`` (A9)."""

    def transcribe_session(
        self,
        *,
        session_id: UUID,
        audio_wav: Path,
        timeline: Sequence[AudioTimelineEntry],
        session_started_at: datetime,
        progress: Callable[[str], None] | None = None,
    ) -> list[TranscriptSegment]: ...


@runtime_checkable
class MeetingNoteRenderer(Protocol):
    """Render the vault-flavoured meeting note (adapter owns template, naming, layout) (A9)."""

    def note_path(self, session: MeetingSession) -> Path | None:
        """Target note path, or ``None`` when the vault export is not configured."""
        ...

    def screenshots_dir(self, note_path: Path) -> Path:
        """Default screenshots directory for images referenced from ``note_path``."""
        ...

    def render(
        self,
        *,
        session: MeetingSession,
        segments: list[TranscriptSegment],
        summary: Summary | None,
        speaker_display: dict[str, str] | None = None,
        transcript_lines: list[str] | None = None,
    ) -> str: ...
