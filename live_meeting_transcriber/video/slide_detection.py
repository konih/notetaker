"""Backward-compatible slide detection entry points (prefer ``video.strategies``)."""

from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.video.slide_common import (
    SlideDetectionError,
    extract_slide_frame,
)
from live_meeting_transcriber.video.strategies.frame_diff import (
    FrameDiffStrategy,
    mean_absolute_difference,
)
from live_meeting_transcriber.video.strategies.frame_diff import (
    mean_absolute_difference as _mean_absolute_difference,
)

__all__ = [
    "SlideCandidate",
    "SlideDetectionError",
    "_mean_absolute_difference",
    "detect_slide_candidates",
    "extract_slide_frame",
    "mean_absolute_difference",
]


def detect_slide_candidates(
    *,
    video_path: Path,
    duration_seconds: float,
    sample_interval_seconds: float,
    change_threshold: float,
    min_slide_interval_seconds: float,
    max_candidates: int,
    preview_dir: Path | None = None,
    thumb_width: int = 160,
    thumb_height: int = 90,
) -> list[SlideCandidate]:
    """Legacy wrapper around :class:`FrameDiffStrategy`."""
    params = SlideDetectionParams(
        sample_interval_seconds=sample_interval_seconds,
        change_threshold=change_threshold,
        min_slide_interval_seconds=min_slide_interval_seconds,
        max_candidates=max_candidates,
    )
    return FrameDiffStrategy().detect(
        video_path=video_path,
        duration_seconds=duration_seconds,
        params=params,
        preview_dir=preview_dir,
        thumb_width=thumb_width,
        thumb_height=thumb_height,
    )
