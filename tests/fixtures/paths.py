"""Paths to test media under ``tests/fixtures/`` (meeting speech + presentations)."""

from __future__ import annotations

from pathlib import Path

_FIXTURES_ROOT = Path(__file__).resolve().parent

# Meeting recorder: spoken English / German (16 kHz mono PCM)
MEETING_EN_WAV = _FIXTURES_ROOT / "wav" / "meeting_en_10s_16k_mono.wav"
MEETING_EN_LONG_WAV = _FIXTURES_ROOT / "wav" / "meeting_en_120s_16k_mono.wav"
MEETING_DE_WAV = _FIXTURES_ROOT / "wav" / "meeting_de_10s_16k_mono.wav"
MEETING_DE_LONG_WAV = _FIXTURES_ROOT / "wav" / "meeting_de_120s_16k_mono.wav"

# Video transcriber: real + synthetic presentations (short + 2-minute)
PRESENTATION_EN_VIDEO = _FIXTURES_ROOT / "video" / "presentation_en_15s_360p.mp4"
PRESENTATION_EN_LONG_VIDEO = _FIXTURES_ROOT / "video" / "presentation_en_120s_360p.mp4"
PRESENTATION_DE_VIDEO = _FIXTURES_ROOT / "video" / "presentation_de_15s_360p.mp4"
PRESENTATION_DE_LONG_VIDEO = _FIXTURES_ROOT / "video" / "presentation_de_120s_360p.mp4"
PRESENTATION_SYNTHETIC_VIDEO = _FIXTURES_ROOT / "sample_presentation.mp4"
PRESENTATION_SYNTHETIC_LONG_VIDEO = _FIXTURES_ROOT / "sample_presentation_120s.mp4"

# Cached full English presentation download (gitignored)
PRESENTATION_EN_SOURCE = _FIXTURES_ROOT / ".cache" / "presentation_en_source.mp4"


def fixtures_available() -> bool:
    """True when core fixtures exist (run ``task fixtures:fetch``)."""
    return (
        MEETING_EN_WAV.is_file()
        and MEETING_EN_LONG_WAV.is_file()
        and MEETING_DE_WAV.is_file()
        and PRESENTATION_EN_VIDEO.is_file()
        and PRESENTATION_EN_LONG_VIDEO.is_file()
        and PRESENTATION_SYNTHETIC_VIDEO.is_file()
    )
