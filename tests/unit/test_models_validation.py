from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from live_meeting_transcriber.domain.models import AudioChunk, TranscriptSegment


def test_audio_chunk_validation_end_after_start() -> None:
    sid = uuid4()
    start = datetime.utcnow()
    with pytest.raises(ValueError):
        AudioChunk(
            session_id=sid,
            started_at=start,
            ended_at=start,
            path=Path("/tmp/x.wav"),
            sample_rate_hz=16000,
            channels=1,
        )


def test_transcript_segment_validation_text_non_empty() -> None:
    sid = uuid4()
    start = datetime.utcnow()
    end = start + timedelta(seconds=1)
    with pytest.raises(ValueError):
        TranscriptSegment(
            session_id=sid,
            started_at=start,
            ended_at=end,
            text="",
        )

