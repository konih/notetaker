from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class SpeakerLabel(str, Enum):
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
    started_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    ended_at: datetime | None = None


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


class TranscriptSegment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    chunk_id: UUID | None = None
    started_at: datetime
    ended_at: datetime
    text: str = Field(min_length=1)
    speaker: SpeakerLabel = SpeakerLabel.unknown
    metadata: ProviderMetadata | None = None

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


class Summary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    summary_markdown: str = Field(min_length=1)
    action_items: list[ActionItem] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    metadata: ProviderMetadata | None = None
