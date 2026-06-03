"""Extract audio and probe duration from video/media files (ffmpeg/ffprobe)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MediaImportError(RuntimeError):
    pass


def probe_media_duration_seconds(path: Path) -> float:
    """Return media duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaImportError("ffprobe not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise MediaImportError((e.stderr or "").strip() or "ffprobe failed") from e

    try:
        payload = json.loads(proc.stdout)
        dur = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        raise MediaImportError("could not parse ffprobe duration") from e
    if dur <= 0:
        raise MediaImportError("media duration must be positive")
    return dur


def extract_audio_to_wav(
    *,
    video_path: Path,
    dest_wav: Path,
    sample_rate_hz: int,
    channels: int,
) -> Path:
    """Demux audio from ``video_path`` into mono/stereo PCM WAV at ``dest_wav``."""
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate_hz),
        "-acodec",
        "pcm_s16le",
        str(dest_wav),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaImportError("ffmpeg not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise MediaImportError((e.stderr or "").strip() or "ffmpeg audio extract failed") from e
    if not dest_wav.is_file():
        raise MediaImportError(f"expected WAV at {dest_wav}")
    return dest_wav
