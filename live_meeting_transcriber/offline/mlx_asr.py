"""MLX (Apple-Silicon GPU) ASR engine for the offline finalize pipeline (F12).

mlx-whisper transcribes on the Apple GPU ~7x faster than the CTranslate2 cpu/int8
baseline at the same model size (measured — see
``docs/spikes/2026-07-11-f11-apple-silicon-asr.md``). This module owns everything
MLX-specific:

- **Engine resolution** for ``OFFLINE_ASR_ENGINE`` (``auto`` | ``whisperx`` | ``mlx``)
  with explicit-wins + graceful-degradation semantics. An unavailable mlx never
  raises ImportError: B3 classifies finalize ImportErrors as unrecoverable and would
  permanently stop auto-retrying a session over a mere engine preference, so the
  resolution degrades to the WhisperX path with a warning instead.
- **The mlx-whisper transcribe call** (word timestamps on; each window decoded with
  ``condition_on_previous_text=False``, the standard anti-hallucination setting for
  VAD-less Whisper — parity with the batched WhisperX baseline, which also decodes
  windows unconditioned).
- **Diarization-turn conversion + overlap speaker assignment**, replacing WhisperX's
  wav2vec2-based ``assign_word_speakers`` on this path (the forced-alignment model is
  a WhisperX internal; the pure assignment lives in
  :mod:`live_meeting_transcriber.domain.speaker_overlap`).

Adapter layer: imports config/domain only, never application/CLI/UI (A9 contracts).
"""

from __future__ import annotations

import platform
import wave
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from live_meeting_transcriber.audio.wav_level import rms_dbfs_window_from_wav_path
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.speaker_overlap import SpeakerTurn, assign_segment_speaker
from live_meeting_transcriber.observability.logging import get_logger

OfflineAsrEngine = Literal["whisperx", "mlx"]


def _platform_probe() -> tuple[str, str]:
    """``(platform.system(), platform.machine())`` — a seam so tests stay hermetic."""
    return platform.system(), platform.machine()


def _mlx_importable() -> bool:
    """Whether the optional ``mlx`` extra is present. Never lets ImportError escape."""
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_offline_asr_engine(
    settings: Settings,
    *,
    mlx_importable: Callable[[], bool] | None = None,
    platform_probe: Callable[[], tuple[str, str]] | None = None,
) -> tuple[OfflineAsrEngine, str | None]:
    """Resolve the effective finalize ASR engine and an optional degradation warning.

    - ``whisperx``: always WhisperX, even when mlx is available.
    - ``auto``: mlx iff running on Apple Silicon (darwin/arm64) with the ``mlx`` extra
      importable — installing the extra is the opt-in — else WhisperX, silently.
    - ``mlx``: mlx when available; otherwise WhisperX with a warning message that the
      caller must surface (returned, not raised — finalize must keep working).

    Probes default to the real platform/import checks; tests inject fakes.
    """
    probe_import = mlx_importable if mlx_importable is not None else _mlx_importable
    probe_platform = platform_probe if platform_probe is not None else _platform_probe

    configured = settings.offline_asr_engine
    if configured == "whisperx":
        return "whisperx", None

    system, machine = probe_platform()
    apple_silicon = system == "Darwin" and machine == "arm64"
    if apple_silicon and probe_import():
        return "mlx", None
    if configured == "mlx":
        if not apple_silicon:
            reason = (
                f"this machine is {system}/{machine}, and MLX needs Apple Silicon (Darwin/arm64)"
            )
        else:
            reason = "the mlx extra is not installed (uv sync --extra mlx)"
        return (
            "whisperx",
            f"OFFLINE_ASR_ENGINE=mlx requested but {reason}; falling back to the WhisperX engine.",
        )
    return "whisperx", None


def run_mlx_asr(
    *,
    audio_wav: Path,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Transcribe ``audio_wav`` with mlx-whisper on the Apple GPU.

    Returns the Whisper result dict (``segments`` with word timestamps, ``language``).
    MLX handles its own GPU placement — none of the CTranslate2 device/compute
    settings apply here. The model repo (``MLX_WHISPER_MODEL``) is downloaded from
    the Hugging Face Hub on first use, like the WhisperX checkpoints.
    """
    import mlx_whisper

    language = settings.whisperx_language
    whisper_lang = None if language in (None, "", "auto") else language

    _step(progress, f"Loading MLX Whisper model {settings.mlx_whisper_model!r} (Apple GPU)…")
    _step(progress, "Transcribing on the Apple GPU (MLX)…")
    result: dict[str, Any] = mlx_whisper.transcribe(
        str(audio_wav),
        path_or_hf_repo=settings.mlx_whisper_model,
        word_timestamps=True,
        language=whisper_lang,
        condition_on_previous_text=False,
        verbose=None,
    )

    # Hallucination-on-silence gate (F11 spike): mlx-whisper decodes without the
    # baseline's external VAD and can invent text over silence. Anything decoded from a
    # window quieter than the gate is dropped — there was nothing to transcribe there.
    kept, dropped = drop_silent_window_segments(
        list(result.get("segments") or []),
        rms_for_window=_wav_window_rms_probe(audio_wav),
        threshold_dbfs=settings.mlx_silence_gate_dbfs,
    )
    if dropped:
        result["segments"] = kept
        _step(
            progress,
            f"Transcribe cleanup: dropped {dropped} silent-window segment(s) "
            f"(hallucination guard, < {settings.mlx_silence_gate_dbfs:.1f} dBFS).",
        )
    return result


def drop_silent_window_segments(
    segments: list[dict[str, Any]],
    *,
    rms_for_window: Callable[[float, float], float],
    threshold_dbfs: float,
) -> tuple[list[dict[str, Any]], int]:
    """Split ``segments`` into (kept, dropped-count) by their window's RMS energy.

    Mirrors F1's conservatism: only a *strictly* quieter window drops (the boundary
    keeps), and an unmeasurable window (NaN) keeps the segment — NaN comparisons are
    false, so the gate fails open by construction.
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for seg in segments:
        rms = rms_for_window(float(seg.get("start", 0.0)), float(seg.get("end", 0.0)))
        if rms < threshold_dbfs:
            dropped += 1
            continue
        kept.append(seg)
    return kept, dropped


def _wav_window_rms_probe(audio_wav: Path) -> Callable[[float, float], float]:
    """Window-RMS reader for ``audio_wav`` that returns NaN instead of raising."""

    def probe(start_seconds: float, end_seconds: float) -> float:
        try:
            return rms_dbfs_window_from_wav_path(audio_wav, start_seconds, end_seconds)
        except (OSError, wave.Error, EOFError):
            return float("nan")

    return probe


def turns_from_diarization(diarize_segments: Any) -> list[SpeakerTurn]:
    """Convert whisperx ``DiarizationPipeline`` output to domain :class:`SpeakerTurn`s.

    The real pipeline returns a pandas DataFrame with ``start``/``end``/``speaker``
    columns; iterables of mappings (or row objects) are accepted too so tests need
    no pandas.
    """
    if hasattr(diarize_segments, "itertuples"):  # pandas DataFrame (whisperx)
        return [
            SpeakerTurn(start=float(row.start), end=float(row.end), speaker=str(row.speaker))
            for row in diarize_segments.itertuples(index=False)
        ]
    out: list[SpeakerTurn] = []
    for row in diarize_segments:
        if isinstance(row, Mapping):
            out.append(
                SpeakerTurn(
                    start=float(row["start"]), end=float(row["end"]), speaker=str(row["speaker"])
                )
            )
        else:
            out.append(
                SpeakerTurn(start=float(row.start), end=float(row.end), speaker=str(row.speaker))
            )
    return out


def apply_overlap_speaker_assignment(result: dict[str, Any], turns: Sequence[SpeakerTurn]) -> None:
    """Set ``seg["speaker"]`` on every result segment via pure overlap assignment.

    Word timestamps missing a start or end are ignored; a segment without usable
    words falls back to its own interval (handled by the domain function).
    """
    for seg in result.get("segments") or []:
        words = [
            (float(w["start"]), float(w["end"]))
            for w in (seg.get("words") or [])
            if w.get("start") is not None and w.get("end") is not None
        ]
        speaker = assign_segment_speaker(
            start=float(seg.get("start", 0.0)),
            end=float(seg.get("end", 0.0)),
            words=words,
            turns=turns,
        )
        if speaker is not None:
            seg["speaker"] = speaker


def _step(progress: Callable[[str], None] | None, message: str) -> None:
    get_logger(component="mlx_finalize").info("finalize_step", message=message)
    if progress is not None:
        progress(message)
