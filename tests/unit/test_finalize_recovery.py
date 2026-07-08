"""Finding sessions that were recorded but never successfully diarized/finalized.

Real-world root cause (confirmed against a copy of a user's actual database):
finalize-on-stop schedules an un-awaited asyncio task and the app exits right
after, killing it before WhisperX finishes. The session keeps its live
"unknown" speakers forever unless someone notices and re-runs finalize by
hand. ``find_unfinalized_sessions`` is the shared query used both by a CLI
backfill command and by app-startup recovery to locate those sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.finalize_service import find_unfinalized_sessions
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection


def _container_with(conn) -> Container:  # type: ignore[no-untyped-def]
    return Container(
        settings=None,  # type: ignore[arg-type]
        _conn=conn,
        devices=None,  # type: ignore[arg-type]
        audio=None,  # type: ignore[arg-type]
        transcriber=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        diarization_segments=None,  # type: ignore[arg-type]
        sessions=SqliteMeetingSessionRepository(conn),
        transcripts=SqliteTranscriptRepository(conn),
        summaries=None,  # type: ignore[arg-type]
        people=None,  # type: ignore[arg-type]
        session_speakers=None,  # type: ignore[arg-type]
    )


def _make_session(
    sessions: SqliteMeetingSessionRepository, *, ended_at: datetime | None
) -> MeetingSession:
    session = MeetingSession(title="t", started_at=datetime(2026, 1, 1, 9, 0, 0), ended_at=None)
    sessions.create(session)
    if ended_at is not None:
        sessions.conn.execute(
            "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
            (ended_at.isoformat(), str(session.id)),
        )
        sessions.conn.commit()
    return session.model_copy(update={"ended_at": ended_at})


def _add_segment(
    transcripts: SqliteTranscriptRepository, session: MeetingSession, speaker: str
) -> None:
    transcripts.append(
        TranscriptSegment(
            session_id=session.id,
            started_at=session.started_at,
            ended_at=session.started_at + timedelta(seconds=1),
            text="hello",
            speaker=speaker,
        )
    )


def test_finds_ended_session_with_all_unknown_transcript(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, session, "unknown")
    _add_segment(c.transcripts, session, "unknown")

    found = find_unfinalized_sessions(container=c)

    assert [s.id for s in found] == [session.id]


def test_skips_session_with_a_real_speaker_label(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, session, "unknown")
    _add_segment(c.transcripts, session, "speaker_1")

    assert find_unfinalized_sessions(container=c) == []


def test_skips_session_still_recording(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, ended_at=None)
    _add_segment(c.transcripts, session, "unknown")

    assert find_unfinalized_sessions(container=c) == []


def test_skips_session_with_no_transcript(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    _make_session(c.sessions, ended_at=datetime(2026, 1, 1, 10, 0, 0))

    assert find_unfinalized_sessions(container=c) == []


def test_ended_after_bounds_the_recovery_window(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    old_session = _make_session(c.sessions, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, old_session, "unknown")
    recent_session = _make_session(c.sessions, ended_at=datetime(2026, 6, 1, 10, 0, 0))
    _add_segment(c.transcripts, recent_session, "unknown")

    found = find_unfinalized_sessions(container=c, ended_after=datetime(2026, 5, 1, 0, 0, 0))

    assert [s.id for s in found] == [recent_session.id]
