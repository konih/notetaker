"""Video import settings: slide detection for ``live-transcriber transcribe-video``."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

from live_meeting_transcriber.domain.models import SlideDetectionParams


class VideoSettings(BaseSettings):
    """Slide-change detection knobs for imported presentation videos."""

    video_slide_strategy: Literal["frame_diff", "ffmpeg_scene"] = Field(
        default="frame_diff", alias="VIDEO_SLIDE_STRATEGY"
    )
    video_slide_sample_interval_seconds: float = Field(
        default=2.0, alias="VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS", ge=0.5, le=30.0
    )
    video_slide_change_threshold: float = Field(
        default=0.12, alias="VIDEO_SLIDE_CHANGE_THRESHOLD", ge=0.01, le=1.0
    )
    video_slide_min_interval_seconds: float = Field(
        default=15.0, alias="VIDEO_SLIDE_MIN_INTERVAL_SECONDS", ge=0.0, le=600.0
    )
    video_slide_max_candidates: int = Field(
        default=120, alias="VIDEO_SLIDE_MAX_CANDIDATES", ge=1, le=500
    )

    def slide_detection_params(self) -> SlideDetectionParams:
        """Build domain slide detection params from current settings."""
        return SlideDetectionParams(
            sample_interval_seconds=self.video_slide_sample_interval_seconds,
            change_threshold=self.video_slide_change_threshold,
            min_slide_interval_seconds=self.video_slide_min_interval_seconds,
            max_candidates=self.video_slide_max_candidates,
        )
