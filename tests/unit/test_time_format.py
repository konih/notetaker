from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from live_meeting_transcriber.utils.time import (
    format_clock,
    format_duration,
    format_local_datetime,
    format_relative,
)

# A fixed non-UTC zone so tests are deterministic regardless of the CI machine's TZ.
PLUS2 = timezone(timedelta(hours=2))


def test_format_clock_converts_to_given_local_zone() -> None:
    dt = datetime(2026, 7, 8, 9, 14, 0, tzinfo=UTC)
    assert format_clock(dt, tz=PLUS2) == "11:14:00"


def test_format_clock_treats_naive_as_utc() -> None:
    # Legacy DB rows may be naive (see A11); display must not crash and assumes UTC.
    dt = datetime(2026, 7, 8, 9, 0, 0)
    assert format_clock(dt, tz=UTC) == "09:00:00"


def test_format_local_datetime() -> None:
    dt = datetime(2026, 7, 8, 9, 14, 30, tzinfo=UTC)
    assert format_local_datetime(dt, tz=PLUS2) == "2026-07-08 11:14"


def test_format_duration_minutes_seconds() -> None:
    assert format_duration(0) == "00:00"
    assert format_duration(65) == "01:05"
    assert format_duration(599) == "09:59"


def test_format_duration_hours() -> None:
    assert format_duration(3661) == "1:01:01"


def test_format_duration_clamps_negative() -> None:
    assert format_duration(-5) == "00:00"


def test_format_relative_labels() -> None:
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    assert format_relative(now - timedelta(seconds=30), now) == "just now"
    assert format_relative(now - timedelta(minutes=5), now) == "5 min ago"
    assert format_relative(now - timedelta(hours=1), now) == "1 hour ago"
    assert format_relative(now - timedelta(hours=2), now) == "2 hours ago"
    assert format_relative(now - timedelta(days=1), now) == "1 day ago"
    assert format_relative(now - timedelta(days=3), now) == "3 days ago"


def test_format_relative_future_clamps_to_just_now() -> None:
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    assert format_relative(now + timedelta(minutes=5), now) == "just now"
