"""Extract time ranges from PCM WAV files (ffmpeg)."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

from live_meeting_transcriber.domain.exceptions import WavSegmentExtractionError
from live_meeting_transcriber.domain.session_audio import MIN_TRANSCRIPTION_CHUNK_SECONDS

__all__ = [
    "MIN_TRANSCRIPTION_CHUNK_SECONDS",
    "WavSegmentExtractionError",
    "extract_wav_time_range",
    "pcm_wav_duration_seconds",
    "safe_wav_duration_seconds",
    "wav_is_transcribable",
]

# PCM s16le WAV header is 44 bytes; anything smaller is not usable audio.
_MIN_PCM_WAV_BYTES = 44


def pcm_wav_duration_seconds(path: Path) -> float:
    """Duration of a PCM WAV file in seconds (for clipping diarization offsets)."""
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        if rate <= 0:
            return 0.0
        return frames / float(rate)


def safe_wav_duration_seconds(path: Path) -> float:
    """Like :func:`pcm_wav_duration_seconds` but returns ``0.0`` on missing or corrupt files."""
    if not path.is_file():
        return 0.0
    try:
        return pcm_wav_duration_seconds(path)
    except Exception:
        return 0.0


def wav_is_transcribable(
    path: Path, *, min_seconds: float = MIN_TRANSCRIPTION_CHUNK_SECONDS
) -> bool:
    """Return whether ``path`` looks like non-empty audio worth sending to STT."""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= _MIN_PCM_WAV_BYTES:
        return False
    return safe_wav_duration_seconds(path) >= min_seconds


def extract_wav_time_range(
    *,
    src: Path,
    dest: Path,
    start_seconds: float,
    end_seconds: float,
    sample_rate_hz: int,
    channels: int,
) -> None:
    """Write ``dest`` as PCM s16le WAV containing ``[start_seconds, end_seconds)`` of ``src``."""
    if end_seconds <= start_seconds:
        raise WavSegmentExtractionError("end_seconds must be greater than start_seconds")
    duration = end_seconds - start_seconds
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-ss",
        str(start_seconds),
        "-t",
        str(duration),
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate_hz),
        "-acodec",
        "pcm_s16le",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise WavSegmentExtractionError("ffmpeg not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise WavSegmentExtractionError((e.stderr or "").strip() or "ffmpeg failed") from e
