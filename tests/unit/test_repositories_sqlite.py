from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.domain.models import (
    DiarizationSegment,
    MeetingSession,
    SpeakerLabel,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.storage.repositories import (
    SqliteDiarizationRepository,
    SqliteKnownPeopleRepository,
    SqliteMeetingSessionRepository,
    SqliteSessionSpeakerNameRepository,
    SqliteSummaryRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.utils.time import utc_now


def test_repositories_create_list_get_sessions(tmp_path: Path) -> None:
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


def test_legacy_naive_timestamp_reads_back_tz_aware(tmp_path: Path) -> None:
    # A11: rows written before the tz-aware migration (A1) stored naive ISO strings
    # (no "+00:00"). Reading them must coerce to UTC-aware so a later Python-side
    # comparison against tz-aware `utc_now()` cannot raise `TypeError: can't compare
    # offset-naive and offset-aware datetimes`.
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="Legacy"))
        # Simulate an old naive row by rewriting started_at without an offset.
        naive_iso = "2024-01-01T10:00:00"
        assert "+" not in naive_iso and "Z" not in naive_iso
        conn.execute(
            "UPDATE meeting_sessions SET started_at = ? WHERE id = ?",
            (naive_iso, str(s.id)),
        )

        got = sessions.get(s.id)

        assert got is not None
        assert got.started_at.tzinfo is not None, "legacy naive row must read back aware"
        assert got.started_at == datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        # The whole point: this comparison must not raise.
        assert got.started_at < utc_now()
    finally:
        conn.close()


def test_reopen_preserves_title_notes_attendees(tmp_path: Path) -> None:
    # U20 AC4: resuming (reopen) a meeting must not clobber operator-set metadata.
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="Standup"))
        sessions.update_details(
            s.id, title="Standup", notes="Agenda: roadmap", attendees=["Alice", "Bob"]
        )
        sessions.end(s.id)

        reopened = sessions.reopen(s.id)

        assert reopened is not None
        assert reopened.ended_at is None
        assert reopened.title == "Standup"
        assert reopened.notes == "Agenda: roadmap"
        assert reopened.attendees == ["Alice", "Bob"]
    finally:
        conn.close()


def test_meeting_session_update_title(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="Old"))
        updated = sessions.update_title(s.id, "New title")
        assert updated is not None
        assert updated.title == "New title"
        fetched = sessions.get(s.id)
        assert fetched is not None
        assert fetched.title == "New title"
    finally:
        conn.close()


def test_repository_append_list_transcript_segments(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)

        s = sessions.create(MeetingSession(title="X"))
        start = utc_now()
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


def test_transcript_replace_session(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)
        s = sessions.create(MeetingSession(title="X"))
        start = utc_now()
        transcripts.append(
            TranscriptSegment(
                session_id=s.id,
                started_at=start,
                ended_at=start + timedelta(seconds=1),
                text="old",
            )
        )
        new_segments = [
            TranscriptSegment(
                session_id=s.id,
                started_at=start,
                ended_at=start + timedelta(seconds=2),
                text="a",
                speaker="YOU",
            ),
            TranscriptSegment(
                session_id=s.id,
                started_at=start + timedelta(seconds=2),
                ended_at=start + timedelta(seconds=3),
                text="b",
                speaker="REMOTE",
            ),
        ]
        transcripts.replace_session_transcript(s.id, new_segments)
        got = transcripts.list_by_session(s.id)
        assert [g.text for g in got] == ["a", "b"]
        assert [g.speaker for g in got] == ["YOU", "REMOTE"]
    finally:
        conn.close()


def test_meeting_session_notes_and_attendees(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="M", notes="N1", attendees=["Alice"]))
        got = sessions.get(s.id)
        assert got is not None
        assert got.notes == "N1"
        assert got.attendees == ["Alice"]
        u = sessions.update_details(s.id, notes="N2", attendees=["Bob", "Carol"])
        assert u is not None
        assert u.notes == "N2"
        assert u.attendees == ["Bob", "Carol"]
    finally:
        conn.close()


def test_known_people_and_session_speaker_names(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        people = SqliteKnownPeopleRepository(conn)
        sessions = SqliteMeetingSessionRepository(conn)
        spk = SqliteSessionSpeakerNameRepository(conn)
        people.touch("Frederik")
        people.touch("frederik")
        assert "Frederik" in people.search_prefix("f", limit=5)
        s = sessions.create(MeetingSession(title="Meet"))
        spk.replace_map(s.id, {"speaker_1": "Frederik"})
        assert spk.get_map(s.id) == {"speaker_1": "Frederik"}
    finally:
        conn.close()


def test_transcript_update_segment_text(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)
        s = sessions.create(MeetingSession(title="X"))
        start = utc_now()
        seg = TranscriptSegment(
            session_id=s.id,
            started_at=start,
            ended_at=start + timedelta(seconds=1),
            text="old",
            speaker=SpeakerLabel.speaker_1,
        )
        transcripts.append(seg)
        upd = transcripts.update_segment_text(seg.id, "new text")
        assert upd is not None
        assert upd.text == "new text"
        assert transcripts.list_by_session(s.id)[0].text == "new text"
    finally:
        conn.close()


def test_meeting_session_reopen_clears_ended_at(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        s = sessions.create(MeetingSession(title="Reopen me"))
        sessions.end(s.id)
        ended = sessions.get(s.id)
        assert ended is not None
        assert ended.ended_at is not None
        reopened = sessions.reopen(s.id)
        assert reopened is not None
        assert reopened.ended_at is None
        assert sessions.reopen(uuid4()) is None
    finally:
        conn.close()


def test_meeting_session_delete_cascades_related_rows(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)
        summaries = SqliteSummaryRepository(conn)
        spk = SqliteSessionSpeakerNameRepository(conn)

        s = sessions.create(MeetingSession(title="To delete"))
        start = utc_now()
        seg = TranscriptSegment(
            session_id=s.id,
            started_at=start,
            ended_at=start + timedelta(seconds=1),
            text="line",
            speaker=SpeakerLabel.speaker_1,
        )
        transcripts.append(seg)
        summaries.upsert(
            Summary(
                session_id=s.id, summary_markdown="# Notes\n\nHello.", action_items=[], decisions=[]
            )
        )
        spk.replace_map(s.id, {"speaker_1": "Alice"})

        assert sessions.delete(s.id) is True
        assert sessions.get(s.id) is None
        assert transcripts.list_by_session(s.id) == []
        assert summaries.get_by_session(s.id) is None
        assert spk.get_map(s.id) == {}
        assert sessions.delete(s.id) is False
    finally:
        conn.close()


def test_diarization_repository_and_session_delete(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        diar = SqliteDiarizationRepository(conn)
        s = sessions.create(MeetingSession(title="D"))
        t0 = utc_now()
        t1 = t0 + timedelta(seconds=2)
        seg = DiarizationSegment(started_at=t0, ended_at=t1, speaker_key="speaker_1")
        diar.append_segments(s.id, [seg])
        listed = diar.list_by_session(s.id)
        assert len(listed) == 1
        assert listed[0].speaker_key == "speaker_1"
        assert sessions.delete(s.id) is True
        assert diar.list_by_session(s.id) == []
    finally:
        conn.close()


def test_session_speaker_set_alias_and_list(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        spk = SqliteSessionSpeakerNameRepository(conn)
        s = sessions.create(MeetingSession(title="A"))
        spk.set_alias(s.id, "speaker_1", "Konrad")
        assert spk.get_map(s.id) == {"speaker_1": "Konrad"}
        als = spk.list_aliases(s.id)
        assert len(als) == 1
        assert als[0].display_name == "Konrad"
    finally:
        conn.close()


def test_transcript_update_segment_speaker(tmp_path: Path) -> None:
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        sessions = SqliteMeetingSessionRepository(conn)
        transcripts = SqliteTranscriptRepository(conn)
        s = sessions.create(MeetingSession(title="X"))
        start = utc_now()
        seg = TranscriptSegment(
            session_id=s.id,
            started_at=start,
            ended_at=start + timedelta(seconds=1),
            text="t",
            speaker="unknown",
        )
        transcripts.append(seg)
        upd = transcripts.update_segment_speaker(seg.id, "speaker_2")
        assert upd is not None
        assert upd.speaker == "speaker_2"
    finally:
        conn.close()
