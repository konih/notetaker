"""F2: SessionService.search_sessions filters the stored sessions by metadata."""

from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.storage.repositories import SqliteMeetingSessionRepository
from live_meeting_transcriber.storage.sqlite import open_connection


def _service(conn: object) -> SessionService:
    sessions = SqliteMeetingSessionRepository(conn)  # type: ignore[arg-type]
    return SessionService(
        sessions=sessions,
        transcripts=None,  # type: ignore[arg-type]
        summaries=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
    )


def test_search_sessions_filters_by_title(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        svc = _service(conn)
        svc.sessions.create(MeetingSession(title="Platform Review"))
        svc.sessions.create(MeetingSession(title="Budget Planning"))

        results = svc.search_sessions("platform")
        assert [s.title for s in results] == ["Platform Review"]
    finally:
        conn.close()


def test_search_sessions_empty_query_lists_all(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        svc = _service(conn)
        svc.sessions.create(MeetingSession(title="A"))
        svc.sessions.create(MeetingSession(title="B"))

        assert len(svc.search_sessions("")) == 2
    finally:
        conn.close()
