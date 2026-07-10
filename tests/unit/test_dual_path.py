"""Shared dual_path capability predicate + downgrade reason (D4, DOC-03/ROUGH-03)."""

from __future__ import annotations

from live_meeting_transcriber.application.dual_path import (
    dual_path_downgrade_reason,
    transcriber_supports_dual_path,
)


class _StereoCapable:
    def transcribe_stereo_chunk(self, **_kwargs: object) -> list[object]:
        return []


class _MonoOnly:
    pass


def test_supports_dual_path_predicate() -> None:
    assert transcriber_supports_dual_path(_StereoCapable()) is True
    assert transcriber_supports_dual_path(_MonoOnly()) is False
    assert transcriber_supports_dual_path(None) is False


def test_no_reason_when_mode_is_mixdown() -> None:
    assert (
        dual_path_downgrade_reason(
            audio_stereo_mode="mixdown", audio_channels=2, transcriber=_MonoOnly()
        )
        is None
    )


def test_no_reason_when_dual_path_fully_supported() -> None:
    assert (
        dual_path_downgrade_reason(
            audio_stereo_mode="dual_path", audio_channels=2, transcriber=_StereoCapable()
        )
        is None
    )


def test_reason_when_transcriber_incapable() -> None:
    reason = dual_path_downgrade_reason(
        audio_stereo_mode="dual_path", audio_channels=2, transcriber=_MonoOnly()
    )
    assert reason is not None
    assert "faster_whisper" in reason


def test_reason_when_not_two_channels() -> None:
    reason = dual_path_downgrade_reason(
        audio_stereo_mode="dual_path", audio_channels=1, transcriber=_StereoCapable()
    )
    assert reason is not None
    assert "AUDIO_CHANNELS" in reason
