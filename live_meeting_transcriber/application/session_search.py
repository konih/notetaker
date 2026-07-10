"""Session search/filter over metadata — pure, no I/O (F2).

Case-insensitive substring match across a session's title, notes, and attendees. This is
the shared core of the ``sessions --search`` CLI (and, later, a TUI filter box — see U17).

Scope note (F2): metadata only. Full transcript-text search, date-range filters, and
SQL-side pushdown are deliberately out of scope here — the session count is small enough to
filter in memory, and transcript search needs a separate index. Imports only the domain
model, so it stays on the right side of the hexagon.
"""

from __future__ import annotations

from live_meeting_transcriber.domain.models import MeetingSession


def session_matches(session: MeetingSession, query: str) -> bool:
    """True if ``query`` (case-insensitive) is a substring of any searchable field.

    An empty/whitespace query matches every session (so callers can pass the raw flag).
    """
    q = query.strip().lower()
    if not q:
        return True
    haystacks = [session.title, session.notes, *session.attendees]
    return any(q in (field or "").lower() for field in haystacks)


def filter_sessions(sessions: list[MeetingSession], query: str) -> list[MeetingSession]:
    """Return the sessions matching ``query``; an empty query returns a copy of all."""
    if not query.strip():
        return list(sessions)
    return [s for s in sessions if session_matches(s, query)]
