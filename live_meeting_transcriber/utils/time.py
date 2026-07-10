from __future__ import annotations

from datetime import UTC, datetime, tzinfo


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_aware(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC.

    Legacy DB rows written before the tz-aware migration may be naive (see roadmap A11);
    callers must not crash on them and assume they were UTC. The storage read boundary
    (`repositories._dt_from_str`) coerces here so nothing downstream sees a naive value.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def to_local(dt: datetime, tz: tzinfo | None = None) -> datetime:
    """Convert ``dt`` to local time (or an explicit ``tz`` for deterministic tests)."""
    return ensure_aware(dt).astimezone(tz)


def format_clock(dt: datetime, tz: tzinfo | None = None) -> str:
    """Local wall-clock time, ``HH:MM:SS`` (e.g. transcript line prefixes)."""
    return to_local(dt, tz).strftime("%H:%M:%S")


def format_local_datetime(dt: datetime, tz: tzinfo | None = None) -> str:
    """Local date + time, ``YYYY-MM-DD HH:MM`` (e.g. session catalog rows)."""
    return to_local(dt, tz).strftime("%Y-%m-%d %H:%M")


def elapsed_seconds(start: datetime, now: datetime) -> float:
    """Seconds between ``start`` and ``now``, treating naive inputs as UTC (see A11).

    Guards against the ``aware - naive`` ``TypeError`` that would otherwise crash callers
    (e.g. the per-second elapsed timer) if a legacy naive timestamp slips through.
    """
    return (ensure_aware(now) - ensure_aware(start)).total_seconds()


def format_duration(seconds: float) -> str:
    """Elapsed span as ``MM:SS``, or ``H:MM:SS`` once it reaches an hour. Negatives clamp to 0."""
    total = int(max(0.0, seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_relative(dt: datetime, now: datetime) -> str:
    """Human relative label for ``dt`` compared to ``now`` (both may be naive → UTC).

    ``now`` is an explicit parameter (not read internally) so callers control the clock
    and tests stay deterministic. Future/skewed timestamps clamp to ``"just now"``.
    """
    secs = (ensure_aware(now) - ensure_aware(dt)).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        hours = int(secs // 3600)
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    days = int(secs // 86400)
    return f"{days} day ago" if days == 1 else f"{days} days ago"
