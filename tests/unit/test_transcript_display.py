"""Unit tests for Meetings tab transcript formatting."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.ui.tui.transcript_display import (
    format_meeting_transcript_line,
    format_meeting_transcript_text,
    format_segment_timestamp,
    segment_offset_seconds,
)


def _segment(*, start_sec: float, text: str, speaker: str = "speaker_1") -> TranscriptSegment:
    session_start = datetime(2025, 6, 3, 10, 0, 0)
    started = session_start + timedelta(seconds=start_sec)
    return TranscriptSegment(
        session_id=uuid4(),
        started_at=started,
        ended_at=started + timedelta(seconds=2),
        text=text,
        speaker=speaker,
    )


def test_segment_offset_seconds_clamps_negative() -> None:
    session_start = datetime(2025, 6, 3, 10, 0, 0)
    seg = _segment(start_sec=-5, text="early")
    assert segment_offset_seconds(seg, session_start) == 0.0


def test_format_segment_timestamp_short_and_long() -> None:
    session_start = datetime(2025, 6, 3, 10, 0, 0)
    assert format_segment_timestamp(_segment(start_sec=65, text="a"), session_start) == "[1:05]"
    assert (
        format_segment_timestamp(_segment(start_sec=3661, text="b"), session_start) == "[1:01:01]"
    )


def test_format_meeting_transcript_line_includes_speaker_and_full_text() -> None:
    session_start = datetime(2025, 6, 3, 10, 0, 0)
    seg = _segment(start_sec=12, text="Hello\nworld", speaker="speaker_1")
    line = format_meeting_transcript_line(
        seg,
        session_start,
        {"speaker_1": "Alice"},
    )
    assert line == "[0:12] Alice: Hello world"


def test_format_meeting_transcript_text_joins_all_segments() -> None:
    session = MeetingSession(id=uuid4(), title="Demo", started_at=datetime(2025, 6, 3, 10, 0, 0))
    segments = [
        _segment(start_sec=0, text="First", speaker="unknown"),
        _segment(start_sec=30, text="Second", speaker="speaker_2"),
    ]
    body = format_meeting_transcript_text(segments, session)
    assert "[0:00] Unknown Speaker: First" in body
    assert "[0:30] Speaker 2: Second" in body
    assert body.count("\n") == 1


def test_format_meeting_transcript_text_empty() -> None:
    session = MeetingSession(id=uuid4(), title="Empty", started_at=datetime(2025, 6, 3, 10, 0, 0))
    assert "No transcript" in format_meeting_transcript_text([], session)
