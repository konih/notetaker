"""F1: energy-based silence skipping — pure decision + RMS measurement.

Quiet chunks waste transcription tokens (OpenAI) or compute (faster-whisper).
The skip decision is a pure function on the chunk's RMS level in dBFS; the
measurement is a dependency-free PCM scan (no VAD model). These tests exercise
both against synthesized PCM: digital silence, a quiet speech-like sine, and
loud noise.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from live_meeting_transcriber.application.silence import should_skip_silent_chunk
from live_meeting_transcriber.audio.wav_level import rms_dbfs_from_wav_path

from tests.unit.conftest import write_wav


def _sine(amplitude: float, *, seconds: float = 0.5, freq_hz: float = 220.0) -> list[float]:
    n = int(16000 * seconds)
    return [amplitude * math.sin(2 * math.pi * freq_hz * i / 16000) for i in range(n)]


# --- measurement: rms_dbfs_from_wav_path ---------------------------------------------


def test_rms_digital_silence_is_minus_infinity(tmp_path: Path) -> None:
    p = write_wav(tmp_path / "silence.wav", [0.0] * 8000)
    assert rms_dbfs_from_wav_path(p) == float("-inf")


def test_rms_empty_wav_is_minus_infinity(tmp_path: Path) -> None:
    p = write_wav(tmp_path / "empty.wav", [])
    assert rms_dbfs_from_wav_path(p) == float("-inf")


def test_rms_quiet_sine_measures_expected_level(tmp_path: Path) -> None:
    # Sine RMS = amplitude / sqrt(2); at amplitude 0.02 that is about -37 dBFS —
    # quiet-speech territory, far above the skip threshold.
    p = write_wav(tmp_path / "quiet.wav", _sine(0.02))
    expected = 20 * math.log10(0.02 / math.sqrt(2))
    assert abs(rms_dbfs_from_wav_path(p) - expected) < 1.0


def test_rms_loud_noise_is_high(tmp_path: Path) -> None:
    rng = random.Random(42)
    samples = [rng.uniform(-0.9, 0.9) for _ in range(8000)]
    p = write_wav(tmp_path / "loud.wav", samples)
    assert rms_dbfs_from_wav_path(p) > -10.0


def test_rms_near_silence_is_below_default_threshold(tmp_path: Path) -> None:
    # Amplitude 1e-4 sine ≈ -83 dBFS RMS: true digital near-silence, below -70.
    p = write_wav(tmp_path / "near_silence.wav", _sine(0.0001))
    assert rms_dbfs_from_wav_path(p) < -70.0


def test_rms_stereo_wav_supported(tmp_path: Path) -> None:
    # Interleave a loud left channel with a silent right channel; overall RMS
    # must still register the energy (never skip when one channel has speech).
    left = _sine(0.5, seconds=0.25)
    interleaved: list[float] = []
    for s in left:
        interleaved.extend((s, 0.0))
    p = write_wav(tmp_path / "stereo.wav", interleaved, channels=2)
    assert rms_dbfs_from_wav_path(p) > -20.0


# --- decision: should_skip_silent_chunk (pure) ----------------------------------------


def test_skip_when_enabled_and_below_threshold() -> None:
    assert should_skip_silent_chunk(enabled=True, rms_dbfs=-85.0, threshold_dbfs=-70.0) is True


def test_no_skip_when_above_threshold() -> None:
    assert should_skip_silent_chunk(enabled=True, rms_dbfs=-37.0, threshold_dbfs=-70.0) is False


def test_no_skip_at_exact_threshold() -> None:
    # Boundary is inclusive-keep: only strictly quieter than the threshold skips.
    assert should_skip_silent_chunk(enabled=True, rms_dbfs=-70.0, threshold_dbfs=-70.0) is False


def test_no_skip_when_disabled() -> None:
    assert (
        should_skip_silent_chunk(enabled=False, rms_dbfs=float("-inf"), threshold_dbfs=-70.0)
        is False
    )


def test_digital_silence_skips_when_enabled() -> None:
    assert (
        should_skip_silent_chunk(enabled=True, rms_dbfs=float("-inf"), threshold_dbfs=-70.0) is True
    )


def test_nan_energy_fails_open() -> None:
    # An unmeasurable level must never cause a skip — losing speech is worse
    # than transcribing silence.
    assert (
        should_skip_silent_chunk(enabled=True, rms_dbfs=float("nan"), threshold_dbfs=-70.0) is False
    )
