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


# --- F13: diarization device auto-prefers MPS on Apple Silicon -----------------
# Evidence: docs/spikes/2026-07-11-f11-apple-silicon-asr.md — pyannote 4.x output on
# MPS is byte-identical to CPU on this hardware and ~8-20x faster. Auto only: an
# explicit WHISPERX_DIARIZE_DEVICE (including explicit cpu) always wins.


def test_auto_diarize_device_prefers_mps_on_apple_silicon() -> None:
    assert (
        wp._auto_diarize_device(align_device="cpu", has_mps=True, system="Darwin", machine="arm64")
        == "mps"
    )


def test_auto_diarize_device_cpu_when_mps_unavailable_on_apple_silicon() -> None:
    assert (
        wp._auto_diarize_device(align_device="cpu", has_mps=False, system="Darwin", machine="arm64")
        == "cpu"
    )


def test_auto_diarize_device_darwin_intel_never_mps() -> None:
    assert (
        wp._auto_diarize_device(
            align_device="cpu", has_mps=False, system="Darwin", machine="x86_64"
        )
        == "cpu"
    )


def test_auto_diarize_device_non_darwin_unchanged() -> None:
    # Non-macOS auto behavior is untouched even if a torch build claims MPS.
    assert (
        wp._auto_diarize_device(align_device="cpu", has_mps=True, system="Linux", machine="x86_64")
        == "cpu"
    )


def test_auto_diarize_device_cuda_alignment_still_prefers_cpu() -> None:
    # The B5 GPU-OOM guard: a second model next to CUDA alignment stays on CPU.
    for system, machine, has_mps in (("Linux", "x86_64", False), ("Darwin", "arm64", True)):
        assert (
            wp._auto_diarize_device(
                align_device="cuda:0", has_mps=has_mps, system=system, machine=machine
            )
            == "cpu"
        )


def test_auto_diarize_device_mps_alignment_without_usable_mps_is_cpu() -> None:
    # Explicit WHISPERX_TORCH_DEVICE=mps while torch reports MPS unavailable -> cpu (B5).
    assert (
        wp._auto_diarize_device(align_device="mps", has_mps=False, system="Linux", machine="x86_64")
        == "cpu"
    )


def test_resolve_diarize_device_auto_mps_on_apple_silicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))
    assert wp._resolve_diarize_device(_settings(whisperx_diarize_device=None), "cpu") == "mps"


def test_resolve_diarize_device_explicit_cpu_beats_auto_mps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))
    assert wp._resolve_diarize_device(_settings(whisperx_diarize_device="cpu"), "cpu") == "cpu"


def test_resolve_diarize_device_explicit_value_returned_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, False))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Linux", "x86_64"))
    assert wp._resolve_diarize_device(_settings(whisperx_diarize_device="mps"), "cpu") == "mps"


def test_resolve_diarize_device_auto_non_darwin_follows_align_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, False))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Linux", "x86_64"))
    assert wp._resolve_diarize_device(_settings(whisperx_diarize_device=None), "cpu") == "cpu"


def test_diarize_device_explicitness_helper() -> None:
    assert wp._diarize_device_is_explicit(_settings(whisperx_diarize_device="mps")) is True
    assert wp._diarize_device_is_explicit(_settings(whisperx_diarize_device="cpu")) is True
    assert wp._diarize_device_is_explicit(_settings(whisperx_diarize_device=None)) is False
