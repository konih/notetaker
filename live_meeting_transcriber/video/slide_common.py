"""Shared ffmpeg helpers for slide detection strategies."""

from __future__ import annotations

import subprocess
from pathlib import Path


class SlideDetectionError(RuntimeError):
    pass


def effective_min_slide_interval(
    min_slide_interval_seconds: float,
    duration_seconds: float,
) -> float:
    """Cap pacing so short clips can retain multiple slide candidates.

    Default ``VIDEO_SLIDE_MIN_INTERVAL_SECONDS=15`` is tuned for hour-long
    talks; on a 15 s fixture it would suppress every transition after t=0.
    """
    if min_slide_interval_seconds <= 0 or duration_seconds <= 0:
        return min_slide_interval_seconds
    cap = max(2.0, duration_seconds / 3.0)
    return min(min_slide_interval_seconds, cap)


def extract_slide_frame(
    *,
    video_path: Path,
    timestamp_seconds: float,
    dest_png: Path,
    width: int | None = None,
) -> Path:
    """Write a PNG still from ``video_path`` at ``timestamp_seconds``."""
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    vf_parts: list[str] = []
    if width is not None and width > 0:
        vf_parts.append(f"scale={width}:-1")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(max(0.0, timestamp_seconds)),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
    ]
    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
    cmd.append(str(dest_png))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SlideDetectionError("ffmpeg not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise SlideDetectionError((e.stderr or "").strip() or "ffmpeg slide extract failed") from e
    if not dest_png.is_file():
        raise SlideDetectionError(f"expected PNG at {dest_png}")
    return dest_png


def extract_gray_frame_bytes(
    *,
    video_path: Path,
    timestamp_seconds: float,
    width: int,
    height: int,
) -> bytes:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, timestamp_seconds)),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height},format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise SlideDetectionError("ffmpeg not found; install ffmpeg") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode(errors="replace").strip()
        raise SlideDetectionError(detail or "ffmpeg frame extract failed") from e
    return proc.stdout


def maybe_save_preview(
    *,
    video_path: Path,
    timestamp_seconds: float,
    preview_dir: Path | None,
    index: int,
) -> Path | None:
    if preview_dir is None:
        return None
    dest = preview_dir / f"candidate_{index:03d}_{timestamp_seconds:.1f}s.png"
    try:
        return extract_slide_frame(
            video_path=video_path,
            timestamp_seconds=timestamp_seconds,
            dest_png=dest,
            width=320,
        )
    except SlideDetectionError:
        return None
