#!/usr/bin/env python3
"""Generate a tiny synthetic presentation video for tests (no network)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SystemExit("ffmpeg not found; run scripts/install_video_prereqs.sh") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise SystemExit(detail or "ffmpeg failed") from e


_DEFAULT_COLORS: tuple[str, ...] = (
    "0x2244AA",
    "0xAA4422",
    "0x22AA44",
    "0x8844AA",
    "0xAA8844",
    "0x448888",
    "0x666666",
    "0xAA2288",
)


def _slide_colors(count: int) -> tuple[str, ...]:
    if count <= 0:
        raise ValueError("slide count must be positive")
    return tuple(_DEFAULT_COLORS[i % len(_DEFAULT_COLORS)] for i in range(count))


def generate_sample_video(
    dest: Path,
    *,
    slide_seconds: float = 15.0,
    slides: tuple[str, ...] | None = None,
    slide_count: int | None = None,
    width: int = 640,
    height: int = 360,
) -> Path:
    """Build an MP4 with solid-color slides and a sine tone (for audio extract tests)."""
    if slides is None:
        n = slide_count if slide_count is not None else 3
        slides = _slide_colors(n)
    elif slide_count is not None:
        raise ValueError("pass slides or slide_count, not both")

    dest = dest.expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="notetaker-sample-") as tmp:
        tmp_path = Path(tmp)
        parts: list[Path] = []
        for i, color in enumerate(slides):
            part = tmp_path / f"part_{i:02d}.mp4"
            _run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s={width}x{height}:d={slide_seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={440 + i * 110}:duration={slide_seconds}",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ar",
                    "16000",
                    str(part),
                ]
            )
            parts.append(part)

        list_file = tmp_path / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p}'" for p in parts) + "\n",
            encoding="utf-8",
        )
        _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(dest),
            ]
        )

    if not dest.is_file():
        raise SystemExit(f"failed to write {dest}")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("tests/fixtures/sample_presentation.mp4"),
        help="Output MP4 path",
    )
    parser.add_argument(
        "--slide-seconds",
        type=float,
        default=15.0,
        help="Seconds per solid-color slide",
    )
    parser.add_argument(
        "--slide-count",
        type=int,
        default=3,
        help="Number of slides (ignored when --colors is set)",
    )
    parser.add_argument(
        "--colors",
        nargs="+",
        default=None,
        help="Explicit slide colors (hex); overrides --slide-count",
    )
    args = parser.parse_args(argv)
    colors = tuple(args.colors) if args.colors else None
    out = generate_sample_video(
        args.output,
        slide_seconds=args.slide_seconds,
        slides=colors,
        slide_count=None if colors else args.slide_count,
    )
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
