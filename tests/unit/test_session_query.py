"""U17/U11 — pure session query layer (application/session_search.py).

U17 extends F2's metadata substring search with ``after:``/``before:`` date tokens so the
Meetings-tab filter can cover "at least title and date range" without any SQL or I/O.
U11 adds a pure fuzzy (subsequence) matcher for the jump-to-meeting picker.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from live_meeting_transcriber.application.session_search import (
    apply_session_query,
    fuzzy_match,
    parse_session_query,
)
from live_meeting_transcriber.domain.models import MeetingSession


def _session(title: str, started: str) -> MeetingSession:
    return MeetingSession(
        title=title,
        started_at=datetime.fromisoformat(started).replace(tzinfo=UTC),
    )


JULY_1 = _session("Weekly sync", "2026-07-01T12:00:00")
JULY_10 = _session("Design review", "2026-07-10T12:00:00")
JULY_20 = _session("Retro", "2026-07-20T12:00:00")
ALL = [JULY_1, JULY_10, JULY_20]


# --- parse_session_query ---------------------------------------------------


def test_parse_extracts_date_tokens_and_free_text() -> None:
    q = parse_session_query("standup after:2026-07-01 before:2026-07-31")
    assert q.text == "standup"
    assert q.after == date(2026, 7, 1)
    assert q.before == date(2026, 7, 31)


def test_parse_without_tokens_is_all_text() -> None:
    q = parse_session_query("weekly sync")
    assert q.text == "weekly sync"
    assert q.after is None and q.before is None


def test_parse_unparseable_date_token_falls_back_to_text() -> None:
    # A typo'd date must not silently filter everything out — treat it as search text.
    q = parse_session_query("after:notadate foo")
    assert q.after is None
    assert "after:notadate" in q.text and "foo" in q.text


# --- apply_session_query ---------------------------------------------------


def test_after_filters_inclusively() -> None:
    out = apply_session_query(ALL, "after:2026-07-10", tz=UTC)
    assert out == [JULY_10, JULY_20]


def test_before_filters_inclusively() -> None:
    out = apply_session_query(ALL, "before:2026-07-10", tz=UTC)
    assert out == [JULY_1, JULY_10]


def test_date_range_and_text_combine() -> None:
    out = apply_session_query(ALL, "review after:2026-07-02 before:2026-07-19", tz=UTC)
    assert out == [JULY_10]


def test_empty_query_returns_everything() -> None:
    assert apply_session_query(ALL, "   ", tz=UTC) == ALL


def test_text_part_reuses_metadata_substring_semantics() -> None:
    # F2's session_matches covers title/notes/attendees; the query layer must not
    # narrow that to title-only.
    s = MeetingSession(
        title="Untitled",
        started_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
        attendees=["Alice", "Bob"],
    )
    assert apply_session_query([s], "alice", tz=UTC) == [s]


# --- fuzzy_match (U11 jump picker) ----------------------------------------


def test_fuzzy_substring_matches() -> None:
    assert fuzzy_match("sync", "Weekly sync")


def test_fuzzy_subsequence_matches() -> None:
    assert fuzzy_match("wkly", "Weekly sync")
    assert fuzzy_match("dsgn", "Design review")


def test_fuzzy_rejects_non_subsequence() -> None:
    assert not fuzzy_match("xyz", "Weekly sync")
    assert not fuzzy_match("syncs", "Weekly sync")  # extra char beyond the text


def test_fuzzy_is_case_insensitive_and_empty_matches_all() -> None:
    assert fuzzy_match("WEEKLY", "weekly sync")
    assert fuzzy_match("", "anything")
