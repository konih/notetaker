"""Characterization of finalize_service._as_utc (T2, A11 boundary).

A pre-existing DB mixes naive (pre-A1) and tz-aware (post-A1) ``ended_at`` rows;
comparing the two in the recovery-window scan raises ``TypeError``. ``_as_utc``
coerces naive datetimes to UTC so the comparison never throws. Lock that.
"""

from __future__ import annotations

from datetime import UTC, datetime

from live_meeting_transcriber.application.finalize_service import _as_utc


def test_naive_datetime_is_coerced_to_utc() -> None:
    naive = datetime(2026, 1, 1, 12, 0, 0)
    out = _as_utc(naive)
    assert out.tzinfo is UTC
    assert out == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_aware_datetime_is_returned_unchanged() -> None:
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _as_utc(aware) is aware


def test_coerced_naive_and_aware_are_comparable() -> None:
    # The exact A11 failure mode: a naive (old) row vs an aware (new) cutoff.
    naive_row = datetime(2026, 5, 1, 9, 0, 0)
    aware_cutoff = datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC)
    # Would raise "can't compare offset-naive and offset-aware" without coercion.
    assert _as_utc(naive_row) > _as_utc(aware_cutoff)
