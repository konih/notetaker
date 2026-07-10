"""B5: WhisperX ASR device/compute resolution must be valid on Apple Silicon.

WhisperX's ASR backend is CTranslate2, which supports only CPU and CUDA — it has **no**
MPS/Metal backend (``device='mps'`` raises ``ValueError: unsupported device mps``). The
default ``WHISPERX_COMPUTE_TYPE=float16`` is likewise invalid on CPU. So on an Apple-Silicon
machine the auto-resolved defaults (mps + float16) crash finalize before it produces anything.
These tests pin the correct resolution.
"""

from __future__ import annotations

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.offline import whisperx_pipeline as wp


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


# --- auto device selection ---------------------------------------------------
def test_auto_asr_device_prefers_cuda() -> None:
    assert wp._auto_asr_device(has_cuda=True) == "cuda"


def test_auto_asr_device_without_cuda_is_cpu_never_mps() -> None:
    # Apple Silicon has mps but no cuda; CTranslate2 cannot use mps -> cpu.
    assert wp._auto_asr_device(has_cuda=False) == "cpu"


def test_resolve_asr_device_auto_mps_only_uses_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exact regression: (has_cuda=False, has_mps=True) previously returned 'mps'.
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    assert wp._resolve_asr_device(_settings()) == "cpu"


def test_resolve_asr_device_auto_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (True, False))
    assert wp._resolve_asr_device(_settings()) == "cuda"


def test_resolve_asr_device_auto_cpu_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, False))
    assert wp._resolve_asr_device(_settings()) == "cpu"


# --- explicit override -------------------------------------------------------
def test_resolve_asr_device_coerces_explicit_mps_to_cpu() -> None:
    # An operator setting WHISPERX_DEVICE=mps would otherwise crash the ASR.
    assert wp._resolve_asr_device(_settings(whisperx_device="mps")) == "cpu"


def test_resolve_asr_device_respects_explicit_cuda() -> None:
    assert wp._resolve_asr_device(_settings(whisperx_device="cuda")) == "cuda"


def test_resolve_asr_device_respects_explicit_cpu() -> None:
    assert wp._resolve_asr_device(_settings(whisperx_device="cpu")) == "cpu"


# --- compute type ------------------------------------------------------------
def test_compute_type_coerced_to_int8_on_cpu() -> None:
    # Default float16 is invalid on CPU (CTranslate2) -> coerce to int8.
    assert wp._resolve_compute_type(_settings(whisperx_compute_type="float16"), "cpu") == "int8"


def test_compute_type_int8_float16_also_coerced_on_cpu() -> None:
    assert (
        wp._resolve_compute_type(_settings(whisperx_compute_type="int8_float16"), "cpu") == "int8"
    )


def test_compute_type_float16_kept_on_cuda() -> None:
    assert wp._resolve_compute_type(_settings(whisperx_compute_type="float16"), "cuda") == "float16"


def test_compute_type_explicit_cpu_safe_choice_respected() -> None:
    assert wp._resolve_compute_type(_settings(whisperx_compute_type="float32"), "cpu") == "float32"
