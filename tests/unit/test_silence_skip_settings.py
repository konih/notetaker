"""F1: silence-skip settings exist with conservative defaults.

Defaults are asserted on the field metadata (not an instantiated ``Settings``) so a
developer's real ``config.yaml`` / ``.env`` cannot leak into the test.
"""

from __future__ import annotations

from live_meeting_transcriber.config.settings import Settings


def test_silence_skip_enabled_field() -> None:
    field = Settings.model_fields["audio_silence_skip_enabled"]
    assert field.alias == "AUDIO_SILENCE_SKIP_ENABLED"
    assert field.default is True


def test_silence_threshold_field() -> None:
    field = Settings.model_fields["audio_silence_threshold_dbfs"]
    assert field.alias == "AUDIO_SILENCE_THRESHOLD_DBFS"
    # Conservative default: only true digital near-silence sits below -70 dBFS RMS;
    # quiet speech (~-40 dBFS) stays far above it.
    assert field.default == -70.0
