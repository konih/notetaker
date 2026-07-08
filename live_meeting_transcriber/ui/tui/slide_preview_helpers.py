"""Helpers for TUI slide preview (params, formatting, external viewer)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from live_meeting_transcriber.application.slide_review import format_timestamp
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.video.strategies.factory import SlideStrategyName

_IMAGE_WIDGET_CLASS: type | None = None
_IMAGE_WIDGET_CHECKED = False
_INLINE_IMAGES_SUPPORTED: bool | None = None
_INLINE_IMAGE_MODE: str | None = None

_SLIDE_DETECTION_HELP = """\
[bold]frame_diff[/] — Sample frames on an interval; flag when pixel change exceeds threshold.
Good default for screen shares and steady slide decks.

[bold]ffmpeg_scene[/] — Uses ffmpeg scene-change detection; can catch hard cuts faster on some videos.

[bold]Sample interval[/] — Seconds between frame samples (lower = more CPU, finer search).

[bold]Threshold[/] — frame_diff sensitivity; [italic]lower = more sensitive[/] (more candidates).

[bold]Min interval[/] — Minimum seconds between accepted slides (reduces duplicates).

[bold]Max candidates[/] — Upper bound on rows returned per preview run.
"""

_SLIDE_PARAM_HINTS: dict[str, str] = {
    "slide-strategy": "frame_diff: pixel diff between samples · ffmpeg_scene: ffmpeg scene filter",
    "slide-sample": "Seconds between samples (lower = slower, more thorough)",
    "slide-threshold": "Lower = more sensitive (more slide candidates)",
    "slide-min-interval": "Minimum seconds between detected slides",
    "slide-max-candidates": "Cap on candidates per preview run",
}


def ensure_textual_image_protocol_probe() -> None:
    """Import textual-image before Textual starts (required for protocol detection).

    Importing ``textual_image.renderable`` auto-detects the terminal graphics
    protocol, which puts stdin into cbreak mode via ``termios``. When stdout is a
    TTY but stdin is not (e.g. launched through ``task tui`` or with redirected
    stdin), that raises ``termios.error: Operation not supported by device`` —
    which is not an ``ImportError``. Swallow any probe failure so the TUI still
    starts; inline-image detection just falls back gracefully.
    """
    try:
        import textual_image.renderable  # noqa: F401
    except Exception:
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
    except Exception:
        # Not installed (ImportError) or terminal-probe failure (termios.error on
        # non-TTY stdin); either way inline images are unavailable.
        _IMAGE_WIDGET_CLASS = None
    return _IMAGE_WIDGET_CLASS


def _probe_inline_image_mode() -> str:
    """Classify inline preview support (run before Textual starts)."""
    term = os.environ.get("TERM_PROGRAM", "").strip().lower()
    if term in ("kitty", "wezterm", "ghostty"):
        return "graphics"
    try:
        from textual_image.renderable import Image as AutoImage
        from textual_image.renderable.halfcell import Image as HalfcellImage
        from textual_image.renderable.sixel import Image as SixelImage
        from textual_image.renderable.tgp import Image as TGPImage
    except Exception:
        # Missing dependency or terminal-probe failure (termios.error on non-TTY stdin).
        return "none"
    if AutoImage is TGPImage or AutoImage is SixelImage:
        return "graphics"
    if AutoImage is HalfcellImage:
        return "halfcell"
    return "unicode"


def terminal_supports_inline_images() -> bool:
    """Kitty TGP / Sixel / known graphics terminals; not Terminator half-cell fallback."""
    global _INLINE_IMAGES_SUPPORTED, _INLINE_IMAGE_MODE
    if _INLINE_IMAGES_SUPPORTED is None:
        _INLINE_IMAGE_MODE = _probe_inline_image_mode()
        _INLINE_IMAGES_SUPPORTED = _INLINE_IMAGE_MODE == "graphics"
    return _INLINE_IMAGES_SUPPORTED


def inline_image_mode_label() -> str:
    if _INLINE_IMAGE_MODE is None:
        terminal_supports_inline_images()
    return _INLINE_IMAGE_MODE or "none"


def inline_image_unsupported_message() -> str:
    return (
        "[yellow]Inline images need Kitty, WezTerm, or Ghostty[/] "
        "(Terminator and classic xterm cannot show PNGs inline).\n"
        "Press [bold]o[/] to open the preview in your image viewer (xdg-open).\n"
        "[dim]See docs/install-desktop.md · optional: install[/] [bold]chafa[/] "
        "[dim]for ASCII preview here[/]"
    )


def slide_detection_help_text() -> str:
    return _SLIDE_DETECTION_HELP


def slide_param_focus_hint(widget_id: str) -> str:
    return _SLIDE_PARAM_HINTS.get(widget_id, "Select a field above for a short hint.")


def try_chafa_ascii_preview(path: Path, *, columns: int = 48, rows: int = 16) -> str | None:
    """Render PNG to ANSI art when ``chafa`` is installed; otherwise None."""
    if not path.is_file():
        return None
    chafa = shutil.which("chafa")
    if chafa is None:
        return None
    try:
        proc = subprocess.run(
            [chafa, "-s", f"{columns}x{rows}", str(path.resolve())],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.rstrip()


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
    path = cand.preview_path.name if cand.preview_path is not None else "—"
    return (
        f"[bold]#{index + 1}[/] · [cyan]{ts}[/] · score [bold]{cand.change_score:.2f}[/] · "
        f"[{mark}] · [dim]{path}[/]"
    )


def format_candidate_count_hint(
    *,
    count: int,
    duration_seconds: float,
    min_interval_seconds: float,
) -> str:
    """Hint when candidate count looks high or low vs video length."""
    if duration_seconds <= 0:
        return f"{count} candidate(s)"
    interval = min_interval_seconds if min_interval_seconds > 0 else 15.0
    expected = max(1, round(duration_seconds / interval))
    base = f"{count} candidate(s) in {duration_seconds:.0f}s — expect ~{expected} with min interval {interval:.0f}s"
    if count > expected * 2:
        return f"{base} · [yellow]many — raise threshold or min interval[/]"
    if count < max(1, expected // 3) and count > 0:
        return f"{base} · [yellow]few — lower threshold or sample interval[/]"
    return base


def format_review_summary(*, kept: int, skipped: int, total: int) -> str:
    pending = total - kept - skipped
    parts = [f"kept {kept}", f"skipped {skipped}", f"total {total}"]
    if pending > 0:
        parts.append(f"unreviewed {pending}")
    return " · ".join(parts)


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
