"""F13 runtime safety: auto-chosen MPS diarization falls back to CPU on failure.

The F13 auto-upgrade (diarize on MPS on Apple Silicon) must never make finalize
LESS reliable than the previous CPU default: if the pyannote pipeline raises on the
auto-chosen ``mps`` device, finalize retries once on CPU with a logged warning and
continues. Explicit ``WHISPERX_DIARIZE_DEVICE`` choices never retry — the operator
asked for that device, so its errors propagate unchanged.

The wrapper is tested pure (injected ``run``); the wiring test drives the real
``run_whisperx_finalize`` body against a fake ``whisperx`` module, so no torch,
model download, or GPU is needed (unit CI has none of them).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.offline import whisperx_pipeline as wp


def _settings(**overrides: object) -> Settings:
    # These tests exercise WhisperX-path specifics (its diarize fallback); pin the
    # engine so OFFLINE_ASR_ENGINE=auto cannot divert to MLX on an Apple-Silicon dev
    # machine with the mlx extra installed (F12).
    overrides.setdefault("offline_asr_engine", "whisperx")
    return Settings(**overrides)  # type: ignore[arg-type]


# --- the pure retry wrapper ----------------------------------------------------
def test_fallback_retries_on_cpu_when_auto_mps_fails() -> None:
    calls: list[str] = []

    def run(device: str) -> str:
        calls.append(device)
        if device == "mps":
            raise RuntimeError("MPS backend blew up")
        return "SEGMENTS"

    messages: list[str] = []
    out = wp._run_diarization_with_fallback(
        run=run, device="mps", allow_cpu_fallback=True, progress=messages.append
    )
    assert out == "SEGMENTS"
    assert calls == ["mps", "cpu"]
    assert any("retrying on 'cpu'" in m for m in messages), messages


def test_fallback_not_applied_for_explicit_device() -> None:
    def run(device: str) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        wp._run_diarization_with_fallback(
            run=run, device="mps", allow_cpu_fallback=False, progress=None
        )


def test_fallback_no_retry_when_first_attempt_succeeds() -> None:
    calls: list[str] = []

    def run(device: str) -> str:
        calls.append(device)
        return "SEGMENTS"

    out = wp._run_diarization_with_fallback(
        run=run, device="mps", allow_cpu_fallback=True, progress=None
    )
    assert out == "SEGMENTS"
    assert calls == ["mps"]


def test_fallback_cpu_failure_propagates_even_when_auto() -> None:
    # Auto-chosen cpu must not "retry on cpu" (an infinite-ish no-op).
    def run(device: str) -> str:
        raise RuntimeError("cpu failed")

    with pytest.raises(RuntimeError, match="cpu failed"):
        wp._run_diarization_with_fallback(
            run=run, device="cpu", allow_cpu_fallback=True, progress=None
        )


def test_fallback_logs_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, dict[str, Any]]] = []

    class FakeLogger:
        def info(self, event: str, **kw: Any) -> None:  # _progress_step logs info
            pass

        def warning(self, event: str, **kw: Any) -> None:
            warnings.append((event, kw))

    monkeypatch.setattr(wp, "get_logger", lambda **_kw: FakeLogger())

    def run(device: str) -> str:
        if device == "mps":
            raise RuntimeError("MPS backend blew up")
        return "SEGMENTS"

    wp._run_diarization_with_fallback(run=run, device="mps", allow_cpu_fallback=True, progress=None)
    assert warnings, "the CPU fallback must be logged as a warning"
    event, kw = warnings[0]
    assert event == "diarize_device_fallback"
    assert kw.get("device") == "mps"
    assert "MPS backend blew up" in str(kw.get("error"))


# --- wiring: run_whisperx_finalize retries only for the auto-chosen device -----
def _install_fake_whisperx(
    monkeypatch: pytest.MonkeyPatch, *, devices_seen: list[str], fail_on: frozenset[str]
) -> None:
    wx: Any = ModuleType("whisperx")
    dz: Any = ModuleType("whisperx.diarize")

    class _Model:
        def transcribe(self, audio: Any, **kw: Any) -> dict[str, Any]:
            return {
                "segments": [{"start": 0.0, "end": 1.5, "text": " hello world "}],
                "language": "en",
            }

    class DiarizationPipeline:
        def __init__(
            self,
            *,
            token: str | None = None,
            use_auth_token: str | None = None,
            device: str | None = None,
        ) -> None:
            self.device = str(device)

        def __call__(self, audio: Any, **kw: Any) -> str:
            devices_seen.append(self.device)
            if self.device in fail_on:
                raise RuntimeError(f"fake diarization failure on {self.device}")
            return "DIARIZE_SEGMENTS"

    def assign_word_speakers(diarize_segments: Any, result: dict[str, Any]) -> dict[str, Any]:
        assert diarize_segments == "DIARIZE_SEGMENTS"
        for seg in result["segments"]:
            seg["speaker"] = "SPEAKER_00"
        return result

    wx.load_audio = lambda path: "AUDIO"
    wx.load_model = lambda name, device, **kw: _Model()
    wx.assign_word_speakers = assign_word_speakers
    dz.DiarizationPipeline = DiarizationPipeline
    wx.diarize = dz
    monkeypatch.setitem(sys.modules, "whisperx", wx)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", dz)


def _finalize(settings: Settings, tmp_path: Path, progress: list[str]) -> list[Any]:
    wav = tmp_path / "full_session.wav"
    wav.write_bytes(b"not a real wav")
    return wp.run_whisperx_finalize(
        session_id=uuid4(),
        audio_wav=wav,
        timeline=[],
        session_started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
        settings=settings,
        progress=progress.append,
    )


def test_finalize_falls_back_to_cpu_when_auto_mps_diarization_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    devices_seen: list[str] = []
    _install_fake_whisperx(monkeypatch, devices_seen=devices_seen, fail_on=frozenset({"mps"}))
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))

    progress: list[str] = []
    segments = _finalize(
        _settings(
            hf_token="hf_test_token",
            whisperx_skip_alignment=True,
            whisperx_diarize_device=None,
        ),
        tmp_path,
        progress,
    )

    assert devices_seen == ["mps", "cpu"], "must attempt auto mps, then retry on cpu"
    assert len(segments) == 1
    assert segments[0].text == "hello world"
    assert segments[0].speaker == "SPEAKER_00"
    assert any("Loading diarization model on 'mps'" in m for m in progress)
    assert any("retrying on 'cpu'" in m for m in progress)
    assert any("Loading diarization model on 'cpu'" in m for m in progress)


def test_finalize_explicit_mps_failure_propagates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    devices_seen: list[str] = []
    _install_fake_whisperx(monkeypatch, devices_seen=devices_seen, fail_on=frozenset({"mps"}))
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))

    progress: list[str] = []
    with pytest.raises(RuntimeError, match="fake diarization failure on mps"):
        _finalize(
            _settings(
                hf_token="hf_test_token",
                whisperx_skip_alignment=True,
                whisperx_diarize_device="mps",
            ),
            tmp_path,
            progress,
        )
    assert devices_seen == ["mps"], "an explicit device must never silently retry elsewhere"


def test_finalize_auto_mps_success_needs_no_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    devices_seen: list[str] = []
    _install_fake_whisperx(monkeypatch, devices_seen=devices_seen, fail_on=frozenset())
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: ("Darwin", "arm64"))

    progress: list[str] = []
    segments = _finalize(
        _settings(
            hf_token="hf_test_token",
            whisperx_skip_alignment=True,
            whisperx_diarize_device=None,
        ),
        tmp_path,
        progress,
    )
    assert devices_seen == ["mps"]
    assert len(segments) == 1
    assert segments[0].speaker == "SPEAKER_00"
