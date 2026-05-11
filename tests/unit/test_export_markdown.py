from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.application.export_markdown import build_session_export_markdown
from live_meeting_transcriber.domain.models import (
    MeetingSession,
    SpeakerLabel,
    Summary,
    TranscriptSegment,
)


def test_build_session_export_markdown_includes_transcript() -> None:
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 12, 0, 0)
    session = MeetingSession(id=sid, title="Test meet", started_at=t0, ended_at=None)
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        text="Hello",
        speaker=SpeakerLabel.unknown,
    )
    md = build_session_export_markdown(session=session, segments=[seg], summary=None)
    assert "Test meet" in md
    assert "Hello" in md
    assert str(sid) in md
    assert "Unknown Speaker" in md


def test_export_speaker_label_and_alias() -> None:
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 12, 0, 0)
    session = MeetingSession(id=sid, title="S", started_at=t0, ended_at=None)
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        text="Hi",
        speaker="speaker_1",
    )
    md = build_session_export_markdown(
        session=session,
        segments=[seg],
        summary=None,
        speaker_display={"speaker_1": "Konrad"},
    )
    assert "Konrad" in md


def test_build_session_export_markdown_with_summary() -> None:
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 12, 0, 0)
    session = MeetingSession(id=sid, title="S", started_at=t0, ended_at=t0)
    summary = Summary(session_id=sid, summary_markdown="## Done")
    md = build_session_export_markdown(session=session, segments=[], summary=summary)
    assert "## Done" in md
