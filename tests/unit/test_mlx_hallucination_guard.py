"""F12: hallucination-on-silence guard for the MLX finalize engine.

mlx-whisper decodes without the external VAD suppression the batched WhisperX
baseline gets for free; the F11 spike observed a classic "Thank you." hallucination
over a quiet stretch. The guard drops MLX segments whose audio window's RMS energy
sits below ``MLX_SILENCE_GATE_DBFS`` — there was nothing to transcribe there.

Policy mirrors F1's silence-skip conservatism: dropping real speech is far worse
than keeping a hallucination, so the default gate (-60 dBFS) is far below quiet
speech (~-40 dBFS), only a *strictly* quieter window drops, and an unmeasurable
window (unreadable WAV -> NaN) always keeps the segment (fail open).
"""

from __future__ import annotations

import math
import struct
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from live_meeting_transcriber.audio.wav_level import rms_dbfs_window_from_wav_path
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.offline import mlx_asr
from live_meeting_transcriber.offline import whisperx_pipeline as wp
from live_meeting_transcriber.ui.state.finalize_stages import (
    FINALIZE_STAGES,
    select_finalize_stage_index,
)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def _write_tone_then_silence_wav(
    path: Path, *, tone_seconds: float = 2.0, silence_seconds: float = 4.0, rate: int = 16000
) -> None:
    """Mono 16-bit PCM: a clearly audible 440 Hz tone, then digital silence."""
    frames = bytearray()
    for i in range(int(tone_seconds * rate)):
        frames += struct.pack("<h", int(0.3 * 32767 * math.sin(2 * math.pi * 440 * i / rate)))
    frames += b"\x00\x00" * int(silence_seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


# --- window RMS measurement (audio/wav_level.py) ---------------------------------
def test_window_rms_over_tone_is_loud_and_over_silence_is_neg_inf(tmp_path: Path) -> None:
    wav = tmp_path / "t.wav"
    _write_tone_then_silence_wav(wav)
    assert rms_dbfs_window_from_wav_path(wav, 0.0, 2.0) > -30.0
    assert rms_dbfs_window_from_wav_path(wav, 3.0, 5.0) == float("-inf")


def test_window_rms_clamps_past_end_of_file(tmp_path: Path) -> None:
    wav = tmp_path / "t.wav"
    _write_tone_then_silence_wav(wav, tone_seconds=1.0, silence_seconds=0.0)
    # Window extends past EOF: measured over what exists.
    assert rms_dbfs_window_from_wav_path(wav, 0.5, 99.0) > -30.0
    # Entirely past EOF / degenerate: silence.
    assert rms_dbfs_window_from_wav_path(wav, 50.0, 60.0) == float("-inf")
    assert rms_dbfs_window_from_wav_path(wav, 2.0, 1.0) == float("-inf")


# --- the drop policy (pure, injected probe) ---------------------------------------
_SEGS = [
    {"start": 0.0, "end": 2.0, "text": " hello "},
    {"start": 3.0, "end": 5.0, "text": " Thank you. "},
]


def test_drops_only_segments_whose_window_is_below_the_gate() -> None:
    rms = {(0.0, 2.0): -20.0, (3.0, 5.0): -75.0}
    kept, dropped = mlx_asr.drop_silent_window_segments(
        _SEGS, rms_for_window=lambda s, e: rms[(s, e)], threshold_dbfs=-60.0
    )
    assert [s["text"] for s in kept] == [" hello "]
    assert dropped == 1


def test_boundary_keeps_the_segment() -> None:
    kept, dropped = mlx_asr.drop_silent_window_segments(
        _SEGS, rms_for_window=lambda s, e: -60.0, threshold_dbfs=-60.0
    )
    assert dropped == 0 and len(kept) == 2


def test_unmeasurable_window_fails_open() -> None:
    kept, dropped = mlx_asr.drop_silent_window_segments(
        _SEGS, rms_for_window=lambda s, e: float("nan"), threshold_dbfs=-60.0
    )
    assert dropped == 0 and len(kept) == 2


def test_gate_setting_default_and_bounds() -> None:
    assert _settings().mlx_silence_gate_dbfs == -60.0


# --- wiring through the MLX finalize path ------------------------------------------
def _install_fake_mlx_with_hallucination(monkeypatch: pytest.MonkeyPatch) -> None:
    m: Any = ModuleType("mlx_whisper")

    def transcribe(audio: str, **kw: Any) -> dict[str, Any]:
        return {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": " hello there ",
                    "words": [{"word": " hello", "start": 0.0, "end": 2.0}],
                },
                {
                    # The spike's failure mode: text invented over digital silence.
                    "start": 3.0,
                    "end": 5.0,
                    "text": " Thank you. ",
                    "words": [{"word": " Thank", "start": 3.0, "end": 5.0}],
                },
            ],
            "language": "en",
        }

    m.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", m)


def _install_fake_whisperx_diarize(monkeypatch: pytest.MonkeyPatch) -> None:
    wx: Any = ModuleType("whisperx")
    dz: Any = ModuleType("whisperx.diarize")

    class DiarizationPipeline:
        def __init__(self, **kw: Any) -> None:
            pass

        def __call__(self, audio: Any, **kw: Any) -> list[dict[str, Any]]:
            return [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]

    dz.DiarizationPipeline = DiarizationPipeline
    wx.diarize = dz
    monkeypatch.setitem(sys.modules, "whisperx", wx)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", dz)


def test_mlx_finalize_drops_hallucinated_silence_segment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_mlx_with_hallucination(monkeypatch)
    _install_fake_whisperx_diarize(monkeypatch)
    monkeypatch.setattr(mlx_asr, "_mlx_importable", lambda: True)
    monkeypatch.setattr(mlx_asr, "_platform_probe", lambda: ("Darwin", "arm64"))
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))

    wav = tmp_path / "full_session.wav"
    _write_tone_then_silence_wav(wav)

    progress: list[str] = []
    segments = wp.run_whisperx_finalize(
        session_id=uuid4(),
        audio_wav=wav,
        timeline=[],
        session_started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
        settings=_settings(offline_asr_engine="mlx", hf_token="hf_test_token"),
        progress=progress.append,
    )

    assert [s.text for s in segments] == ["hello there"]
    guard_lines = [m for m in progress if "hallucination guard" in m]
    assert len(guard_lines) == 1 and "1" in guard_lines[0]
    # The guard message must read as the transcribe stage (F8 deck monotonicity).
    assert FINALIZE_STAGES[select_finalize_stage_index(guard_lines[0])] == "transcribe"
