"""F2: pure session search/filter over metadata (title, notes, attendees).

Case-insensitive substring match, no I/O — the core of the ``sessions --search`` CLI
and (later) the TUI filter. Transcript full-text search is intentionally out of scope.
"""

from __future__ import annotations

from live_meeting_transcriber.application.session_search import filter_sessions, session_matches
from live_meeting_transcriber.domain.models import MeetingSession


def _s(title: str, *, notes: str = "", attendees: list[str] | None = None) -> MeetingSession:
    return MeetingSession(title=title, notes=notes, attendees=attendees or [])


def test_matches_title_case_insensitive() -> None:
    assert session_matches(_s("Platform Review"), "platform")
    assert session_matches(_s("Platform Review"), "REVIEW")
    assert not session_matches(_s("Platform Review"), "budget")


def test_matches_notes() -> None:
    assert session_matches(_s("Standup", notes="discuss Q3 budget"), "budget")


def test_matches_attendee() -> None:
    assert session_matches(_s("1:1", attendees=["Konrad", "Alex"]), "alex")


def test_empty_or_whitespace_query_matches_everything() -> None:
    assert session_matches(_s("anything"), "")
    assert session_matches(_s("anything"), "   ")


def test_filter_returns_only_matches_preserving_order() -> None:
    sessions = [
        _s("Platform Review"),
        _s("Budget Planning", notes="numbers"),
        _s("Retro", attendees=["Platform team"]),
    ]
    out = filter_sessions(sessions, "platform")
    titles = [s.title for s in out]
    assert titles == ["Platform Review", "Retro"]


def test_filter_empty_query_returns_all_as_new_list() -> None:
    sessions = [_s("a"), _s("b")]
    out = filter_sessions(sessions, "  ")
    assert out == sessions
    assert out is not sessions  # a copy, not the same reference


def test_filter_no_match_returns_empty() -> None:
    assert filter_sessions([_s("a"), _s("b")], "zzz") == []
