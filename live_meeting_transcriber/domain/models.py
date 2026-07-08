from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class SpeakerLabel(str, Enum):
    """Legacy enum for tests and static references; transcript storage uses string keys."""

    unknown = "unknown"
    speaker_1 = "speaker_1"
    speaker_2 = "speaker_2"
    speaker_3 = "speaker_3"
    speaker_4 = "speaker_4"


class ProviderMetadata(BaseModel):
    provider: str
    model: str
    extra: dict[str, Any] = Field(default_factory=dict)


class MeetingSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    ended_at: datetime | None = None
    notes: str = ""
    attendees: list[str] = Field(default_factory=list)


class AudioChunk(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    started_at: datetime
    ended_at: datetime
    path: Path
    sample_rate_hz: int = Field(ge=8000, le=48000)
    channels: int = Field(ge=1, le=2)

    @field_validator("ended_at")
    @classmethod
    def _end_after_start(cls, v: datetime, info: Any) -> datetime:
        started_at = info.data.get("started_at")
        if isinstance(started_at, datetime) and v <= started_at:
            raise ValueError("ended_at must be after started_at")
        return v

    @property
    def duration_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()


class DiarizationSegment(BaseModel):
    """One speaker-homogeneous interval from a diarization run (absolute timestamps)."""

    started_at: datetime
    ended_at: datetime
    speaker_key: str = Field(min_length=1)
    chunk_id: UUID | None = None

    @field_validator("ended_at")
    @classmethod
    def _diar_end_after_start(cls, v: datetime, info: Any) -> datetime:
        started_at = info.data.get("started_at")
        if isinstance(started_at, datetime) and v <= started_at:
            raise ValueError("ended_at must be after started_at")
        return v


class SpeakerAlias(BaseModel):
    """Display name for a diarization speaker key within one session."""

    model_config = {"frozen": True}

    session_id: UUID
    speaker_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class TranscriptSegment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    chunk_id: UUID | None = None
    started_at: datetime
    ended_at: datetime
    text: str = Field(min_length=1)
    speaker: str = Field(default="unknown", min_length=1)
    metadata: ProviderMetadata | None = None

    @field_validator("speaker", mode="before")
    @classmethod
    def _coerce_speaker(cls, v: Any) -> str:
        if isinstance(v, SpeakerLabel):
            return v.value
        s = str(v).strip() if v is not None else "unknown"
        return s if s else "unknown"

    @field_validator("ended_at")
    @classmethod
    def _segment_end_after_start(cls, v: datetime, info: Any) -> datetime:
        started_at = info.data.get("started_at")
        if isinstance(started_at, datetime) and v <= started_at:
            raise ValueError("ended_at must be after started_at")
        return v


class ActionItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    text: str = Field(min_length=1)


class Decision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    text: str = Field(min_length=1)


class MeetingMetadataProposal(BaseModel):
    """Structured meeting metadata from summarization (applied when confidence is set)."""

    title: str | None = None
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    series: str | None = None
    location: str | None = None
    related: str | None = None
    confidence: dict[str, bool] = Field(default_factory=dict)

    def confident_str(self, field: str) -> str | None:
        if not self.confidence.get(field):
            return None
        val = getattr(self, field, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
        return None

    def confident_tags(self) -> list[str]:
        if not self.confidence.get("tags") or not self.tags:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for tag in self.tags:
            t = tag.strip().lower().replace(" ", "-")
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        if "meeting" not in seen:
            out.insert(0, "meeting")
        return out

    def confident_participants(self) -> list[str]:
        if not self.confidence.get("participants"):
            return []
        return [p.strip() for p in self.participants if p.strip()]


class Summary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    summary_markdown: str = Field(min_length=1)
    action_items: list[ActionItem] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    meeting_metadata: MeetingMetadataProposal | None = None
    metadata: ProviderMetadata | None = None


class SlideDetectionParams(BaseModel):
    """Tunable parameters for presentation slide change detection."""

    model_config = {"frozen": True}

    sample_interval_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    change_threshold: float = Field(default=0.12, ge=0.01, le=1.0)
    min_slide_interval_seconds: float = Field(default=15.0, ge=0.0, le=600.0)
    max_candidates: int = Field(default=120, ge=1, le=500)


class SlideCandidate(BaseModel):
    """One detected slide transition at ``timestamp_seconds`` in the source video."""

    model_config = {"frozen": True}

    timestamp_seconds: float
    change_score: float
    preview_path: Path | None = None
