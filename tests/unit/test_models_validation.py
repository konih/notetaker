from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain.models import (
    AudioChunk,
    MeetingSession,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.utils.time import utc_now


def test_audio_chunk_validation_end_after_start() -> None:
    sid = uuid4()
    start = utc_now()
    with pytest.raises(ValueError):
        AudioChunk(
            session_id=sid,
            started_at=start,
            ended_at=start,
            path=Path("/tmp/x.wav"),
            sample_rate_hz=16000,
            channels=1,
        )


def test_default_timestamps_are_timezone_aware() -> None:
    # Default-factory timestamps must be tz-aware UTC so timedelta math and
    # comparisons against utc_now() elsewhere don't raise TypeError (A1).
    assert MeetingSession(title="x").started_at.tzinfo is not None
    assert Summary(session_id=uuid4(), summary_markdown="s").created_at.tzinfo is not None


def test_transcript_segment_validation_text_non_empty() -> None:
    sid = uuid4()
    start = utc_now()
    end = start + timedelta(seconds=1)
    with pytest.raises(ValueError):
        TranscriptSegment(
            session_id=sid,
            started_at=start,
            ended_at=end,
            text="",
        )
