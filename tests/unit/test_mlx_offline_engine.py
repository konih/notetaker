"""F12: MLX (Apple-Silicon GPU) offline ASR engine — selection, fallback, wiring.

The finalize pipeline gains a second ASR engine (mlx-whisper on the Apple GPU,
F11 spike: 7.1x faster than cpu/int8 at equal model size) selected by
``OFFLINE_ASR_ENGINE`` (``auto`` | ``whisperx`` | ``mlx``):

- ``auto`` picks mlx only on darwin/arm64 with the ``mlx`` extra importable
  (installing the extra is the opt-in), else whisperx — never a warning.
- explicit ``whisperx`` always wins, even when mlx is available.
- explicit ``mlx`` on a machine that cannot run it degrades to the whisperx path
  with a logged warning — it must NEVER raise ImportError, because B3 classifies
  finalize ImportErrors as unrecoverable and would permanently stop auto-retrying
  a session over a mere engine preference.

All tests are hermetic: fake ``mlx_whisper`` / ``whisperx`` modules in
``sys.modules`` and injected platform/import probes (unit CI has neither mlx nor
torch).
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
from live_meeting_transcriber.domain.speaker_overlap import SpeakerTurn
from live_meeting_transcriber.offline import mlx_asr
from live_meeting_transcriber.offline import whisperx_pipeline as wp
from pydantic import ValidationError


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


_DARWIN_ARM = ("Darwin", "arm64")
_LINUX_X86 = ("Linux", "x86_64")


# --- settings -----------------------------------------------------------------
def test_offline_asr_engine_defaults_to_auto() -> None:
    s = _settings()
    assert s.offline_asr_engine == "auto"
    assert s.mlx_whisper_model == "mlx-community/whisper-large-v3-turbo"


def test_offline_asr_engine_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        _settings(offline_asr_engine="metal")


# --- engine resolution (pure, injected probes) ----------------------------------
def _resolve(
    engine: str, *, platform: tuple[str, str], importable: bool
) -> tuple[str, str | None]:
    return mlx_asr.resolve_offline_asr_engine(
        _settings(offline_asr_engine=engine),
        mlx_importable=lambda: importable,
        platform_probe=lambda: platform,
    )


def test_auto_prefers_mlx_on_apple_silicon_with_extra() -> None:
    assert _resolve("auto", platform=_DARWIN_ARM, importable=True) == ("mlx", None)


def test_auto_stays_whisperx_off_apple_silicon() -> None:
    assert _resolve("auto", platform=_LINUX_X86, importable=True) == ("whisperx", None)


def test_auto_stays_whisperx_without_the_extra() -> None:
    assert _resolve("auto", platform=_DARWIN_ARM, importable=False) == ("whisperx", None)


def test_explicit_whisperx_wins_even_when_mlx_available() -> None:
    assert _resolve("whisperx", platform=_DARWIN_ARM, importable=True) == ("whisperx", None)


def test_explicit_mlx_selected_when_available() -> None:
    assert _resolve("mlx", platform=_DARWIN_ARM, importable=True) == ("mlx", None)


def test_explicit_mlx_without_extra_degrades_with_warning() -> None:
    engine, warning = _resolve("mlx", platform=_DARWIN_ARM, importable=False)
    assert engine == "whisperx"
    assert warning is not None and "uv sync --extra mlx" in warning


def test_explicit_mlx_on_wrong_platform_degrades_with_warning() -> None:
    engine, warning = _resolve("mlx", platform=_LINUX_X86, importable=True)
    assert engine == "whisperx"
    assert warning is not None and "Apple Silicon" in warning


# --- diarization output -> domain turns -----------------------------------------
def test_turns_from_diarization_accepts_dataframe_like() -> None:
    class _Row:
        def __init__(self, start: float, end: float, speaker: str) -> None:
            self.start, self.end, self.speaker = start, end, speaker

    class _FakeDF:
        def itertuples(self, index: bool = True) -> list[_Row]:
            assert index is False
            return [_Row(0.0, 5.0, "SPEAKER_00"), _Row(6.0, 10.0, "SPEAKER_01")]

    turns = mlx_asr.turns_from_diarization(_FakeDF())
    assert turns == [
        SpeakerTurn(start=0.0, end=5.0, speaker="SPEAKER_00"),
        SpeakerTurn(start=6.0, end=10.0, speaker="SPEAKER_01"),
    ]


def test_turns_from_diarization_accepts_mappings() -> None:
    turns = mlx_asr.turns_from_diarization(
        [{"start": 1.0, "end": 2.0, "speaker": "SPEAKER_03"}]
    )
    assert turns == [SpeakerTurn(start=1.0, end=2.0, speaker="SPEAKER_03")]


# --- pipeline wiring (fake modules; no torch, no GPU, no downloads) --------------
def _install_fake_mlx(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]) -> None:
    m: Any = ModuleType("mlx_whisper")

    def transcribe(audio: str, **kw: Any) -> dict[str, Any]:
        calls.append({"audio": audio, **kw})
        return {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": " hello there ",
                    "words": [
                        {"word": " hello", "start": 0.0, "end": 0.5},
                        # zero-duration word (the spike's mlx quirk)
                        {"word": " there", "start": 1.5, "end": 1.5},
                    ],
                },
                {
                    "start": 6.0,
                    "end": 8.0,
                    "text": " general kenobi ",
                    "words": [
                        {"word": " general", "start": 6.2, "end": 6.8},
                        {"word": " kenobi", "start": 7.0, "end": 7.6},
                    ],
                },
            ],
            "language": "en",
        }

    m.transcribe = transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", m)


def _install_fake_whisperx(
    monkeypatch: pytest.MonkeyPatch, *, allow_asr: bool
) -> dict[str, Any]:
    """Fake whisperx: diarization always available; ASR entry points optional."""
    seen: dict[str, Any] = {"asr_calls": 0, "assign_calls": 0}
    wx: Any = ModuleType("whisperx")
    dz: Any = ModuleType("whisperx.diarize")

    class _Model:
        def transcribe(self, audio: Any, **kw: Any) -> dict[str, Any]:
            return {
                "segments": [{"start": 0.0, "end": 1.5, "text": " from whisperx "}],
                "language": "en",
            }

    def load_model(name: str, device: str, **kw: Any) -> _Model:
        if not allow_asr:
            raise AssertionError("whisperx ASR must not be used on the mlx path")
        seen["asr_calls"] += 1
        return _Model()

    class DiarizationPipeline:
        def __init__(self, **kw: Any) -> None:
            pass

        def __call__(self, audio: Any, **kw: Any) -> list[dict[str, Any]]:
            seen["diarize_audio"] = audio
            return [
                {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
                {"start": 6.0, "end": 10.0, "speaker": "SPEAKER_01"},
            ]

    def assign_word_speakers(diarize_segments: Any, result: dict[str, Any]) -> dict[str, Any]:
        seen["assign_calls"] += 1
        for seg in result["segments"]:
            seg["speaker"] = "SPEAKER_00"
        return result

    wx.load_audio = lambda path: "AUDIO"
    wx.load_model = load_model
    wx.assign_word_speakers = assign_word_speakers
    dz.DiarizationPipeline = DiarizationPipeline
    wx.diarize = dz
    monkeypatch.setitem(sys.modules, "whisperx", wx)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", dz)
    return seen


def _run_finalize(settings: Settings, tmp_path: Path, progress: list[str]) -> list[Any]:
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


def _force_mlx_env(monkeypatch: pytest.MonkeyPatch, *, importable: bool) -> None:
    monkeypatch.setattr(mlx_asr, "_mlx_importable", lambda: importable)
    monkeypatch.setattr(mlx_asr, "_platform_probe", lambda: _DARWIN_ARM)
    monkeypatch.setattr(wp, "_detect_torch_devices", lambda: (False, True))
    monkeypatch.setattr(wp, "_platform_probe", lambda: _DARWIN_ARM)


def test_mlx_engine_transcribes_and_assigns_speakers_by_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    _install_fake_mlx(monkeypatch, calls)
    seen = _install_fake_whisperx(monkeypatch, allow_asr=False)
    _force_mlx_env(monkeypatch, importable=True)

    progress: list[str] = []
    segments = _run_finalize(
        _settings(offline_asr_engine="mlx", hf_token="hf_test_token"), tmp_path, progress
    )

    # mlx got the WAV path and the right decode options.
    assert len(calls) == 1
    assert calls[0]["audio"].endswith("full_session.wav")
    assert calls[0]["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert calls[0]["word_timestamps"] is True
    assert calls[0]["condition_on_previous_text"] is False

    # Speakers come from the pure overlap assignment, not whisperx.assign_word_speakers.
    assert seen["assign_calls"] == 0
    assert [(s.text, s.speaker) for s in segments] == [
        ("hello there", "SPEAKER_00"),
        ("general kenobi", "SPEAKER_01"),
    ]
    meta = segments[0].metadata
    assert meta.provider == "mlx-whisper"
    assert meta.model == "mlx-community/whisper-large-v3-turbo"
    assert meta.extra["offline_finalize"] is True
    assert any("Assigning speakers to words (overlap)" in m for m in progress)
    assert any("MLX pass complete" in m for m in progress)


def test_auto_uses_mlx_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    _install_fake_mlx(monkeypatch, calls)
    _install_fake_whisperx(monkeypatch, allow_asr=False)
    _force_mlx_env(monkeypatch, importable=True)

    segments = _run_finalize(
        _settings(offline_asr_engine="auto", hf_token="hf_test_token"), tmp_path, []
    )
    assert len(calls) == 1
    assert len(segments) == 2


def test_explicit_whisperx_ignores_available_mlx(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    _install_fake_mlx(monkeypatch, calls)
    seen = _install_fake_whisperx(monkeypatch, allow_asr=True)
    _force_mlx_env(monkeypatch, importable=True)

    segments = _run_finalize(
        _settings(
            offline_asr_engine="whisperx",
            hf_token="hf_test_token",
            whisperx_skip_alignment=True,
        ),
        tmp_path,
        [],
    )
    assert calls == []
    assert seen["asr_calls"] == 1
    assert segments[0].metadata.provider == "whisperx"


def test_explicit_mlx_without_extra_falls_back_to_whisperx_not_importerror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B3 guard: an engine preference must degrade, never ImportError-brick the session."""
    seen = _install_fake_whisperx(monkeypatch, allow_asr=True)
    _force_mlx_env(monkeypatch, importable=False)

    progress: list[str] = []
    segments = _run_finalize(
        _settings(
            offline_asr_engine="mlx",
            hf_token="hf_test_token",
            whisperx_skip_alignment=True,
        ),
        tmp_path,
        progress,
    )
    assert seen["asr_calls"] == 1
    assert segments[0].metadata.provider == "whisperx"
    assert any("falling back" in m.lower() for m in progress)


def test_mlx_fallback_never_marks_finalize_unrecoverable() -> None:
    """The degraded engine choice produces no ImportError, so B3's classifier
    (which maps ImportError -> permanent won't-auto-retry marker) stays silent."""
    from live_meeting_transcriber.application.finalize_service import (
        classify_unrecoverable_finalize_error,
    )

    # Sanity-pin B3 semantics: a real ImportError from a missing *whisperx* extra
    # still classifies as unrecoverable; the mlx fallback path simply never raises it
    # (asserted by test_explicit_mlx_without_extra_falls_back_to_whisperx_not_importerror).
    assert classify_unrecoverable_finalize_error(ImportError("x"), session_ended=True)
    assert classify_unrecoverable_finalize_error(RuntimeError("x"), session_ended=True) is None
