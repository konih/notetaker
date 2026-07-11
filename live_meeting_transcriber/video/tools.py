"""Concrete :class:`~live_meeting_transcriber.domain.ports.SlideDetectionTools` (ffmpeg)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.ports import SlideDetectionStrategy
from live_meeting_transcriber.video.slide_common import extract_slide_frame
from live_meeting_transcriber.video.strategies.factory import build_slide_strategy


@dataclass(frozen=True)
class FfmpegSlideDetectionTools:
    """Slide strategy factory + frame extraction behind the ``SlideDetectionTools`` port.

    ``settings`` (when wired by the container) provides the default strategy name for
    ``build_strategy(None)``; without it the factory default (``frame_diff``) applies.
    """

    settings: Settings | None = None

    def build_strategy(self, name: str | None = None) -> SlideDetectionStrategy:
        return build_slide_strategy(name, settings=self.settings)

    def extract_frame(self, *, video_path: Path, timestamp_seconds: float, dest_png: Path) -> Path:
        return extract_slide_frame(
            video_path=video_path, timestamp_seconds=timestamp_seconds, dest_png=dest_png
        )
