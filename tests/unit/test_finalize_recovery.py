"""Finding sessions that were recorded but never successfully diarized/finalized.

Real-world root cause (confirmed against a copy of a user's actual database):
finalize-on-stop schedules an un-awaited asyncio task and the app exits right
after, killing it before WhisperX finishes. The session keeps its live
"unknown" speakers forever unless someone notices and re-runs finalize by
hand. ``find_unfinalized_sessions`` is the shared query used both by a CLI
backfill command and by app-startup recovery to locate those sessions.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.finalize_service import (
    find_unfinalized_sessions,
    session_speakers_are_all_unknown,
)
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.ports import MeetingSessionRepository, TranscriptRepository
from live_meeting_transcriber.storage.repositories import (
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection


def _container_with(conn: sqlite3.Connection) -> Container:
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
    sessions: MeetingSessionRepository,
    conn: sqlite3.Connection,
    *,
    ended_at: datetime | None,
) -> MeetingSession:
    session = MeetingSession(title="t", started_at=datetime(2026, 1, 1, 9, 0, 0), ended_at=None)
    sessions.create(session)
    if ended_at is not None:
        conn.execute(
            "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
            (ended_at.isoformat(), str(session.id)),
        )
        conn.commit()
    return session.model_copy(update={"ended_at": ended_at})


def _add_segment(transcripts: TranscriptRepository, session: MeetingSession, speaker: str) -> None:
    transcripts.append(
        TranscriptSegment(
            session_id=session.id,
            started_at=session.started_at,
            ended_at=session.started_at + timedelta(seconds=1),
            text="hello",
            speaker=speaker,
        )
    )


def test_finds_ended_session_with_all_unknown_transcript(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, session, "unknown")
    _add_segment(c.transcripts, session, "unknown")

    found = find_unfinalized_sessions(container=c)

    assert [s.id for s in found] == [session.id]


def test_skips_session_with_a_real_speaker_label(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, session, "unknown")
    _add_segment(c.transcripts, session, "speaker_1")

    assert find_unfinalized_sessions(container=c) == []


def test_skips_session_still_recording(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=None)
    _add_segment(c.transcripts, session, "unknown")

    assert find_unfinalized_sessions(container=c) == []


def test_skips_session_with_no_transcript(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 10, 0, 0))

    assert find_unfinalized_sessions(container=c) == []


def test_session_speakers_are_all_unknown_detects_unlabelled_finalize(tmp_path: Path) -> None:
    """A finalize that ran but couldn't label anyone (e.g. no HF_TOKEN) leaves the transcript
    all-``unknown`` — callers must be able to tell that apart from a real success."""
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)

    unlabelled = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, unlabelled, "unknown")
    _add_segment(c.transcripts, unlabelled, "unknown")
    assert session_speakers_are_all_unknown(container=c, session_id=unlabelled.id) is True

    labelled = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 11, 0, 0))
    _add_segment(c.transcripts, labelled, "unknown")
    _add_segment(c.transcripts, labelled, "speaker_1")
    assert session_speakers_are_all_unknown(container=c, session_id=labelled.id) is False

    empty = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 12, 0, 0))
    assert session_speakers_are_all_unknown(container=c, session_id=empty.id) is False


def _write_full_session_wav(data_dir: Path, session: MeetingSession) -> Path:
    wav = data_dir / "sessions" / str(session.id) / "full_session.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")  # presence is all that matters here
    return wav


def test_interrupted_session_with_surviving_recording_is_found_when_opted_in(
    tmp_path: Path,
) -> None:
    """A meeting whose recording was interrupted (app crash/force-quit) never got ``ended_at`` set,
    but its ``full_session.wav`` survives — it must be recoverable, opt-in only."""
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    data_dir = tmp_path / "data"
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=None)
    _add_segment(c.transcripts, session, "unknown")
    _write_full_session_wav(data_dir, session)

    # Default call still skips it (looks like it's still recording).
    assert find_unfinalized_sessions(container=c) == []

    found = find_unfinalized_sessions(container=c, include_interrupted=True, data_dir=data_dir)
    assert [s.id for s in found] == [session.id]


def test_interrupted_session_without_a_recording_is_never_surfaced(tmp_path: Path) -> None:
    """``ended_at IS NULL`` with no ``full_session.wav`` = genuinely still recording / nothing
    flushed — must not be offered for finalize even when opted in."""
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    data_dir = tmp_path / "data"
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=None)
    _add_segment(c.transcripts, session, "unknown")

    assert find_unfinalized_sessions(container=c, include_interrupted=True, data_dir=data_dir) == []


def test_interrupted_session_excluded_when_it_is_the_active_session(tmp_path: Path) -> None:
    """The session the user is actively recording must never be re-finalized underneath them."""
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    data_dir = tmp_path / "data"
    c = _container_with(conn)
    session = _make_session(c.sessions, conn, ended_at=None)
    _add_segment(c.transcripts, session, "unknown")
    _write_full_session_wav(data_dir, session)

    found = find_unfinalized_sessions(
        container=c,
        include_interrupted=True,
        data_dir=data_dir,
        exclude_session_id=session.id,
    )
    assert found == []


def test_started_after_bounds_interrupted_sessions(tmp_path: Path) -> None:
    """Startup recovery self-heals a *just-crashed* meeting but must not batch-recover the whole
    history of interrupted sessions on every launch (reconciles B3). ``started_after`` bounds the
    interrupted branch by ``started_at`` (interrupted rows have no ``ended_at`` to bound by)."""
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    data_dir = tmp_path / "data"
    c = _container_with(conn)

    old = _make_session(c.sessions, conn, ended_at=None)
    conn.execute(
        "UPDATE meeting_sessions SET started_at = ? WHERE id = ?",
        (datetime(2026, 1, 1, 9, 0, 0).isoformat(), str(old.id)),
    )
    conn.commit()
    old = old.model_copy(update={"started_at": datetime(2026, 1, 1, 9, 0, 0)})
    _add_segment(c.transcripts, old, "unknown")
    _write_full_session_wav(data_dir, old)

    recent = _make_session(c.sessions, conn, ended_at=None)
    conn.execute(
        "UPDATE meeting_sessions SET started_at = ? WHERE id = ?",
        (datetime(2026, 6, 1, 9, 0, 0).isoformat(), str(recent.id)),
    )
    conn.commit()
    recent = recent.model_copy(update={"started_at": datetime(2026, 6, 1, 9, 0, 0)})
    _add_segment(c.transcripts, recent, "unknown")
    _write_full_session_wav(data_dir, recent)

    found = find_unfinalized_sessions(
        container=c,
        include_interrupted=True,
        data_dir=data_dir,
        started_after=datetime(2026, 5, 1, 0, 0, 0),
    )
    assert [s.id for s in found] == [recent.id]

    # Unbounded (CLI finalize-pending) recovers both.
    both = find_unfinalized_sessions(container=c, include_interrupted=True, data_dir=data_dir)
    assert {s.id for s in both} == {old.id, recent.id}


def test_ended_after_bounds_the_recovery_window(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    c = _container_with(conn)
    old_session = _make_session(c.sessions, conn, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    _add_segment(c.transcripts, old_session, "unknown")
    recent_session = _make_session(c.sessions, conn, ended_at=datetime(2026, 6, 1, 10, 0, 0))
    _add_segment(c.transcripts, recent_session, "unknown")

    found = find_unfinalized_sessions(container=c, ended_after=datetime(2026, 5, 1, 0, 0, 0))

    assert [s.id for s in found] == [recent_session.id]
