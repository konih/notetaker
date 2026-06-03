from __future__ import annotations

import logging

import pytest
from live_meeting_transcriber.observability.logging import parse_log_level


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DEBUG", logging.DEBUG),
        ("debug", logging.DEBUG),
        (" DEBUG ", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARN", logging.WARNING),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("not_a_real_level", logging.INFO),
    ],
)
def test_parse_log_level(raw: str, expected: int) -> None:
    assert parse_log_level(raw) == expected
