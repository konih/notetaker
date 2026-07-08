"""Registry and factory for slide detection strategies."""

from __future__ import annotations

from typing import Literal

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.ports import SlideDetectionStrategy
from live_meeting_transcriber.video.strategies.ffmpeg_scene import FfmpegSceneStrategy
from live_meeting_transcriber.video.strategies.frame_diff import FrameDiffStrategy

SlideStrategyName = Literal["frame_diff", "ffmpeg_scene"]

_STRATEGIES: dict[SlideStrategyName, type[SlideDetectionStrategy]] = {
    "frame_diff": FrameDiffStrategy,
    "ffmpeg_scene": FfmpegSceneStrategy,
}


def available_slide_strategies() -> tuple[SlideStrategyName, ...]:
    return tuple(_STRATEGIES.keys())


def build_slide_strategy(
    name: SlideStrategyName | str | None = None,
    *,
    settings: Settings | None = None,
) -> SlideDetectionStrategy:
    """Instantiate a slide detection strategy by name or from settings."""
    resolved = name
    if resolved is None:
        resolved = "frame_diff" if settings is None else settings.video_slide_strategy
    key = str(resolved).strip().lower()
    if key not in _STRATEGIES:
        allowed = ", ".join(_STRATEGIES)
        msg = f"Unknown slide strategy {name!r}; choose one of: {allowed}"
        raise ValueError(msg)
    return _STRATEGIES[key]()
