from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection


def test_repositories_create_list_get_sessions(tmp_path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        repo = SqliteMeetingSessionRepository(conn)
        session = MeetingSession(title="Test meeting")
        repo.create(session)

        got = repo.get(session.id)
        assert got is not None
        assert got.id == session.id
        assert got.title == "Test meeting"

        sessions = repo.list()
        assert len(sessions) == 1
        assert sessions[0].id == session.id
    finally:
        conn.close()


def test_meeting_session_update_title(tmp_path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="Old"))
        updated = sessions.update_title(s.id, "New title")
        assert updated is not None
        assert updated.title == "New title"
        assert sessions.get(s.id) is not None
        assert sessions.get(s.id).title == "New title"
    finally:
        conn.close()


def test_repository_append_list_transcript_segments(tmp_path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)

        s = sessions.create(MeetingSession(title="X"))
        start = datetime.utcnow()
        seg = TranscriptSegment(
            session_id=s.id,
            started_at=start,
            ended_at=start + timedelta(seconds=2),
            text="hello world",
        )
        transcripts.append(seg)
        got = transcripts.list_by_session(s.id)
        assert [g.text for g in got] == ["hello world"]
        assert got[0].session_id == s.id
    finally:
        conn.close()

