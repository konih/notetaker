"""Helpers for TUI slide preview (params, formatting, external viewer)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from live_meeting_transcriber.application.slide_review import format_timestamp
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.video.strategies.factory import SlideStrategyName

_IMAGE_WIDGET_CLASS: type | None = None
_IMAGE_WIDGET_CHECKED = False


def ensure_textual_image_protocol_probe() -> None:
    """Import textual-image before Textual starts (required for protocol detection)."""
    try:
        import textual_image.renderable  # noqa: F401
    except ImportError:
        pass


def image_widget_class() -> type | None:
    """Return textual-image ``Image`` widget class when installed."""
    global _IMAGE_WIDGET_CLASS, _IMAGE_WIDGET_CHECKED
    if _IMAGE_WIDGET_CHECKED:
        return _IMAGE_WIDGET_CLASS
    _IMAGE_WIDGET_CHECKED = True
    try:
        from textual_image.widget import Image as TUIImage

        _IMAGE_WIDGET_CLASS = TUIImage
    except ImportError:
        _IMAGE_WIDGET_CLASS = None
    return _IMAGE_WIDGET_CLASS


def build_slide_params(
    *,
    sample_interval: str,
    threshold: str,
    min_interval: str,
    max_candidates: str,
    settings: Settings,
) -> SlideDetectionParams:
    """Parse TUI input strings into domain params (defaults from settings on empty)."""
    base = settings.slide_detection_params()

    def _float(raw: str, default: float) -> float:
        text = raw.strip()
        return float(text) if text else default

    def _int(raw: str, default: int) -> int:
        text = raw.strip()
        return int(text) if text else default

    return SlideDetectionParams(
        sample_interval_seconds=_float(sample_interval, base.sample_interval_seconds),
        change_threshold=_float(threshold, base.change_threshold),
        min_slide_interval_seconds=_float(min_interval, base.min_slide_interval_seconds),
        max_candidates=_int(max_candidates, base.max_candidates),
    )


def normalize_strategy(raw: str, *, settings: Settings) -> SlideStrategyName:
    text = raw.strip().lower()
    if text in ("frame_diff", "ffmpeg_scene"):
        return text  # type: ignore[return-value]
    return settings.video_slide_strategy  # type: ignore[return-value]


def format_candidate_label(index: int, cand: SlideCandidate, *, keep: bool | None) -> str:
    ts = format_timestamp(cand.timestamp_seconds)
    mark = "✓" if keep is True else ("✗" if keep is False else "·")
    return f"{index + 1}. {ts}  score={cand.change_score:.2f}  [{mark}]"


def review_keep_flags(review: dict[int, bool | None]) -> list[bool | None]:
    if not review:
        return []
    max_idx = max(review)
    return [review.get(i) for i in range(max_idx + 1)]


def accepted_candidates(
    candidates: list[SlideCandidate], review: dict[int, bool | None]
) -> list[SlideCandidate]:
    flags = review_keep_flags(review)
    if not flags:
        return []
    out: list[SlideCandidate] = []
    for i, cand in enumerate(candidates):
        if i < len(flags) and flags[i] is True:
            out.append(cand)
    return out


def open_image_externally(path: Path) -> bool:
    """Open PNG with xdg-open (Linux) or open (macOS). Returns True if a viewer was launched."""
    if not path.is_file():
        return False
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener is None:
        return False
    subprocess.Popen(
        [opener, str(path.resolve())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True
