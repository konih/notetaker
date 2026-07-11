"""Session search/filter over metadata — pure, no I/O (F2, U17, U11).

Case-insensitive substring match across a session's title, notes, and attendees. This is
the shared core of the ``sessions --search`` CLI and the Meetings-tab filter (U17), which
adds ``after:YYYY-MM-DD``/``before:YYYY-MM-DD`` date tokens on top. ``fuzzy_match`` is the
subsequence matcher behind the jump-to-meeting picker (U11).

Scope note (F2): metadata only. Full transcript-text search and SQL-side pushdown are
deliberately out of scope here — the session count is small enough to filter in memory,
and transcript search needs a separate index. Imports only the domain model, so it stays
on the right side of the hexagon.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, tzinfo

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


@dataclass(frozen=True)
class SessionQuery:
    """A parsed filter query: free text plus an optional inclusive started-date range."""

    text: str
    after: date | None = None
    before: date | None = None


def _parse_date_token(token: str, prefix: str) -> date | None:
    raw = token[len(prefix) :]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_session_query(raw: str) -> SessionQuery:
    """Split ``after:``/``before:`` date tokens out of a raw query string.

    A token with an unparseable date is kept as plain search text — a typo must never
    silently filter every session out.
    """
    text_parts: list[str] = []
    after: date | None = None
    before: date | None = None
    for token in raw.split():
        if token.lower().startswith("after:"):
            parsed = _parse_date_token(token, "after:")
            if parsed is not None:
                after = parsed
                continue
        elif token.lower().startswith("before:"):
            parsed = _parse_date_token(token, "before:")
            if parsed is not None:
                before = parsed
                continue
        text_parts.append(token)
    return SessionQuery(text=" ".join(text_parts), after=after, before=before)


def apply_session_query(
    sessions: list[MeetingSession], raw: str, *, tz: tzinfo | None = None
) -> list[MeetingSession]:
    """Filter ``sessions`` by a raw query: free text (F2 semantics) + date range.

    Date tokens compare the session's *started* calendar date, inclusive on both ends,
    in ``tz`` (defaults to the system local timezone — the same one the UI displays,
    so what you see is what you filter).
    """
    query = parse_session_query(raw)
    out: list[MeetingSession] = []
    for s in sessions:
        started = s.started_at.astimezone(tz).date()
        if query.after is not None and started < query.after:
            continue
        if query.before is not None and started > query.before:
            continue
        if not session_matches(s, query.text):
            continue
        out.append(s)
    return out


def fuzzy_match(query: str, text: str) -> bool:
    """True if ``query`` is a case-insensitive subsequence of ``text``.

    Substrings are subsequences too, so this is a strict superset of substring match;
    an empty query matches everything.
    """
    q = query.strip().lower()
    t = text.lower()
    it = iter(t)
    return all(ch in it for ch in q)
