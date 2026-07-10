"""Full-session WhisperX ASR + alignment + pyannote, with stereo YOU/REMOTE labeling."""

from __future__ import annotations

import gc
import wave
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from live_meeting_transcriber.audio.stereo import (
    LabeledSpan,
    compute_speaker_mic_ratios,
    map_pyannote_to_you_remote,
    read_stereo_pcm,
    you_remote_for_audio_interval,
)
from live_meeting_transcriber.audio.timeline import AudioTimelineEntry, map_audio_time_to_wall
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import ProviderMetadata, TranscriptSegment
from live_meeting_transcriber.observability.logging import get_logger


def _wav_is_stereo(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnchannels() == 2
    except Exception:
        return False


# CTranslate2 (WhisperX's ASR backend) supports only CPU and CUDA — it has no MPS/Metal
# backend, and float16 is not an efficient CPU compute type. On Apple Silicon the naive
# auto-defaults (mps + float16) therefore crash finalize before it produces any transcript.
_CPU_UNSAFE_COMPUTE_TYPES = frozenset({"float16", "int8_float16"})


def _detect_torch_devices() -> tuple[bool, bool]:
    """Return ``(has_cuda, has_mps)``; ``(False, False)`` if torch is unavailable."""
    try:
        import torch
    except ImportError:
        return False, False
    has_cuda = bool(torch.cuda.is_available())
    has_mps = bool(getattr(torch.backends, "mps", None)) and bool(torch.backends.mps.is_available())
    return has_cuda, has_mps


def _auto_asr_device(*, has_cuda: bool) -> str:
    """Pick the WhisperX ASR device. CTranslate2 cannot use MPS, so non-CUDA -> CPU."""
    return "cuda" if has_cuda else "cpu"


def _resolve_asr_device(settings: Settings) -> str:
    """Resolve the WhisperX ASR device. Pure: 'mps' (auto or explicit) becomes 'cpu' because
    CTranslate2 would raise ``ValueError: unsupported device mps``. The effective device is
    surfaced by the finalize progress line, so this does not log."""
    explicit = (settings.whisperx_device or "").strip()
    if explicit:
        device = explicit
    else:
        has_cuda, _has_mps = _detect_torch_devices()
        device = _auto_asr_device(has_cuda=has_cuda)
    return "cpu" if device == "mps" else device


def _resolve_compute_type(settings: Settings, device: str) -> str:
    """Coerce a CPU-invalid compute type (float16) to int8; keep GPU/explicit choices. Pure."""
    compute_type = (settings.whisperx_compute_type or "").strip() or "float16"
    if device == "cpu" and compute_type in _CPU_UNSAFE_COMPUTE_TYPES:
        return "int8"
    return compute_type


def _resolve_torch_device(settings: Settings, asr_device: str) -> str:
    if settings.whisperx_torch_device:
        return settings.whisperx_torch_device.strip()
    return asr_device


def _resolve_diarize_device(settings: Settings, align_device: str) -> str:
    """Prefer CPU for pyannote when alignment already uses a GPU (second model often OOMs there)."""
    explicit = (settings.whisperx_diarize_device or "").strip()
    if explicit:
        return explicit
    al = align_device.strip().lower()
    if al.startswith("cuda") or al.startswith("mps"):
        return "cpu"
    return align_device


def _empty_torch_cache(device: str) -> None:
    try:
        import torch
    except ImportError:
        return
    try:
        if device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        elif device == "mps" and hasattr(torch, "mps"):
            torch.mps.empty_cache()
    except Exception:
        pass


def _progress_step(progress: Callable[[str], None] | None, message: str) -> None:
    get_logger(component="whisperx_finalize").info("finalize_step", message=message)
    if progress is not None:
        progress(message)


def run_whisperx_finalize(
    *,
    session_id: UUID,
    audio_wav: Path,
    timeline: list[AudioTimelineEntry],
    session_started_at: datetime,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
) -> list[TranscriptSegment]:
    """Run WhisperX on ``full_session.wav`` and return new transcript segments (wall-clock times)."""
    import whisperx

    if not audio_wav.is_file():
        raise FileNotFoundError(str(audio_wav))

    _progress_step(progress, "Loading full-session WAV into memory…")
    device = _resolve_asr_device(settings)
    compute_type = _resolve_compute_type(settings, device)
    align_device = _resolve_torch_device(settings, device)
    diarize_device = _resolve_diarize_device(settings, align_device)
    language = settings.whisperx_language
    whisper_lang = None if language in (None, "", "auto") else language

    audio = whisperx.load_audio(str(audio_wav))

    _progress_step(
        progress,
        f"Loading Whisper model {settings.whisperx_model!r} on {device!r} (compute={compute_type!r})…",
    )
    model = whisperx.load_model(
        settings.whisperx_model,
        device,
        compute_type=compute_type,
        language=whisper_lang,
    )
    _progress_step(progress, "Transcribing (this can take several minutes)…")
    result: dict[str, Any] = model.transcribe(
        audio, batch_size=settings.whisperx_batch_size, language=whisper_lang
    )
    n_raw = len(result.get("segments") or [])
    _progress_step(progress, f"Transcribe done ({n_raw} raw segment(s)); unloading model…")
    del model
    gc.collect()
    _empty_torch_cache(device)
    _empty_torch_cache(align_device)
    if diarize_device not in (device, align_device):
        _empty_torch_cache(diarize_device)

    detected_language = str(result.get("language") or whisper_lang or "en")

    if not settings.whisperx_skip_alignment:
        _progress_step(
            progress,
            f"Loading alignment model for language={detected_language!r} on {align_device!r}…",
        )
        model_a, metadata = whisperx.load_align_model(
            language_code=detected_language,
            device=align_device,
        )
        _progress_step(progress, "Aligning word timestamps…")
        result = whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            align_device,
            return_char_alignments=False,
        )
        _progress_step(progress, "Alignment finished.")
        del model_a
        gc.collect()
        _empty_torch_cache(align_device)
        _empty_torch_cache(device)

    hf_token = settings.hf_token
    if hf_token:
        from whisperx.diarize import DiarizationPipeline

        _progress_step(
            progress,
            f"Loading diarization model on {diarize_device!r} (HF token required)…",
        )
        try:
            diarize_model = DiarizationPipeline(token=hf_token, device=diarize_device)
        except TypeError:
            diarize_model = DiarizationPipeline(use_auth_token=hf_token, device=diarize_device)
        diarize_kw: dict[str, int] = {}
        if settings.diarization_min_speakers is not None:
            diarize_kw["min_speakers"] = int(settings.diarization_min_speakers)
        if settings.diarization_max_speakers is not None:
            diarize_kw["max_speakers"] = int(settings.diarization_max_speakers)
        _progress_step(progress, "Running speaker diarization…")
        diarize_segments = diarize_model(audio, **diarize_kw)
        _progress_step(progress, "Assigning speakers to words…")
        result = whisperx.assign_word_speakers(diarize_segments, result)
        _progress_step(progress, "Diarization finished.")
        del diarize_model
        gc.collect()
        _empty_torch_cache(diarize_device)
        _empty_torch_cache(align_device)
        _empty_torch_cache(device)
    else:
        _progress_step(progress, "Skipping diarization (no HF_TOKEN).")

    # Large float32 array; stereo labeling reads the WAV from disk again.
    del audio
    gc.collect()
    _empty_torch_cache(device)
    _empty_torch_cache(align_device)
    _empty_torch_cache(diarize_device)

    max_audio_t = 0.0
    for seg in result.get("segments", []):
        max_audio_t = max(max_audio_t, float(seg.get("end", 0.0)))

    stereo_pcm = read_stereo_pcm(audio_wav) if _wav_is_stereo(audio_wav) else None
    raw_spans_for_ratio: list[LabeledSpan] = []
    for seg in result.get("segments", []):
        spk = seg.get("speaker")
        if isinstance(spk, str) and spk:
            raw_spans_for_ratio.append(
                LabeledSpan(
                    start=float(seg.get("start", 0.0)),
                    end=min(float(seg.get("end", 0.0)), max_audio_t),
                    speaker=spk,
                )
            )

    unique_speakers = {s.speaker for s in raw_spans_for_ratio}
    label_map: dict[str, str] = {}
    if stereo_pcm is not None and raw_spans_for_ratio and len(unique_speakers) >= 2:
        ratios = compute_speaker_mic_ratios(stereo_pcm, raw_spans_for_ratio)
        label_map = map_pyannote_to_you_remote(ratios)

    out: list[TranscriptSegment] = []
    for seg in result.get("segments", []):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        t0 = float(seg.get("start", 0.0))
        t1 = float(min(float(seg.get("end", 0.0)), max_audio_t))
        if t1 <= t0:
            continue
        spk = seg.get("speaker")
        speaker_str = str(spk) if isinstance(spk, str) and spk else "unknown"

        if stereo_pcm is not None:
            if label_map and speaker_str in label_map:
                speaker_str = label_map[speaker_str]
            elif speaker_str == "unknown" or len(unique_speakers) <= 1:
                speaker_str = you_remote_for_audio_interval(stereo_pcm, t0, t1)

        if timeline:
            w0 = map_audio_time_to_wall(timeline, t0)
            w1 = map_audio_time_to_wall(timeline, t1)
        else:
            w0 = session_started_at + timedelta(seconds=t0)
            w1 = session_started_at + timedelta(seconds=t1)

        out.append(
            TranscriptSegment(
                id=uuid4(),
                session_id=session_id,
                chunk_id=None,
                started_at=w0,
                ended_at=w1,
                text=text,
                speaker=speaker_str,
                metadata=ProviderMetadata(
                    provider="whisperx",
                    model=settings.whisperx_model,
                    extra={"language": detected_language, "offline_finalize": True},
                ),
            )
        )

    _progress_step(progress, f"WhisperX pass complete ({len(out)} segment(s)).")
    gc.collect()
    _empty_torch_cache(device)
    _empty_torch_cache(align_device)
    _empty_torch_cache(diarize_device)
    return out
