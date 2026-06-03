from __future__ import annotations

from datetime import datetime, timedelta

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.summarization.service import build_summary_prompt


def test_build_summary_prompt_contains_segments() -> None:
    session = MeetingSession(title="Weekly")
    t0 = datetime.utcnow()
    segs = [
        TranscriptSegment(
            session_id=session.id,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            text="First line",
        ),
        TranscriptSegment(
            session_id=session.id,
            started_at=t0 + timedelta(seconds=1),
            ended_at=t0 + timedelta(seconds=2),
            text="Second line",
        ),
    ]

    prompt = build_summary_prompt(session=session, segments=segs)
    assert "Meeting title: Weekly" in prompt
    assert "First line" in prompt
    assert "Second line" in prompt

    p2 = build_summary_prompt(
        session=session,
        segments=segs,
        speaker_display={"unknown": "Frederik"},
    )
    assert "Frederik" in p2

    s2 = MeetingSession(title="T", attendees=["Alice"], notes="Room A")
    p3 = build_summary_prompt(session=s2, segments=segs)
    assert "Alice" in p3
    assert "Room A" in p3

    p4 = build_summary_prompt(session=session, segments=segs, user_context="Quarterly review")
    assert "Quarterly review" in p4
    assert "Additional context from the user" in p4
