"""F6 — live screen capture settings.

Capturing the operator's screen during a meeting is invasive, so the feature is
privacy-default-OFF and must be enabled explicitly (``LIVE_SCREEN_CAPTURE_ENABLED``).
The interval knob is bounded so a typo can neither hammer the disk (sub-5s) nor
silently never fire (multi-hour).
"""

from __future__ import annotations

from typing import Any

import pytest
from live_meeting_transcriber.config.settings import Settings
from pydantic import ValidationError


def _settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="k", database_url="sqlite:////tmp/t.db", **kwargs)


def test_live_capture_disabled_by_default() -> None:
    # Privacy: screen capture must never be on unless the operator opted in.
    assert _settings().live_screen_capture_enabled is False


def test_live_capture_interval_defaults_to_60s() -> None:
    assert _settings().live_screen_capture_interval_seconds == 60


def test_live_capture_env_aliases() -> None:
    fields = Settings.model_fields
    assert fields["live_screen_capture_enabled"].alias == "LIVE_SCREEN_CAPTURE_ENABLED"
    assert (
        fields["live_screen_capture_interval_seconds"].alias
        == "LIVE_SCREEN_CAPTURE_INTERVAL_SECONDS"
    )


def test_live_capture_constructible_by_field_name() -> None:
    s = _settings(live_screen_capture_enabled=True, live_screen_capture_interval_seconds=30)
    assert s.live_screen_capture_enabled is True
    assert s.live_screen_capture_interval_seconds == 30


@pytest.mark.parametrize("bad", [0, 4, 3601, -1])
def test_live_capture_interval_bounds(bad: int) -> None:
    with pytest.raises(ValidationError):
        _settings(live_screen_capture_interval_seconds=bad)
