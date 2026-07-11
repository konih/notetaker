"""Redesign — humanized Started column in the meetings table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from live_meeting_transcriber.ui.tui.meeting_session_helpers import format_started_cell

_NOW = datetime(2026, 7, 11, 15, 30, 0, tzinfo=UTC)


def test_today_reads_as_word_with_time() -> None:
    started = _NOW - timedelta(hours=2)
    assert format_started_cell(started, _NOW, tz=UTC) == "today 13:30"


def test_yesterday_reads_as_word_with_time() -> None:
    started = _NOW - timedelta(days=1)
    assert format_started_cell(started, _NOW, tz=UTC) == "yesterday 15:30"


def test_older_keeps_full_sortable_date() -> None:
    started = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)
    assert format_started_cell(started, _NOW, tz=UTC) == "2026-07-01 09:00"


def test_naive_timestamp_treated_as_utc() -> None:
    # Legacy rows may be naive (A11); the cell must not crash and assumes UTC.
    started = datetime(2026, 7, 1, 9, 0, 0)
    assert format_started_cell(started, _NOW, tz=UTC) == "2026-07-01 09:00"
