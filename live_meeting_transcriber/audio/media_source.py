"""Resolve a local path or remote URL to a video file on disk."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from live_meeting_transcriber.domain.exceptions import MediaSourceError

__all__ = [
    "MediaSourceError",
    "is_remote_url",
    "media_title_from_source",
    "resolve_media_source",
]

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_remote_url(source: str) -> bool:
    return bool(_URL_RE.match(source.strip()))


def resolve_media_source(*, source: str, download_dir: Path) -> Path:
    """Return a local video file from ``source`` (filesystem path or http(s) URL).

    Remote sources are fetched with ``yt-dlp`` into ``download_dir`` (not committed).
    """
    raw = source.strip()
    if not raw:
        raise MediaSourceError("source must not be empty")

    if is_remote_url(raw):
        return _download_with_ytdlp(url=raw, download_dir=download_dir)

    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise MediaSourceError(f"Video file not found: {path}")
    return path


def media_title_from_source(source: str, video_path: Path) -> str:
    """Best-effort title for a new session."""
    if is_remote_url(source.strip()):
        parsed = urlparse(source.strip())
        if parsed.path:
            tail = Path(parsed.path).name
            if tail and tail not in (".", "/"):
                return tail.replace("_", " ").replace("-", " ").strip() or video_path.stem
    return video_path.stem.replace("_", " ").replace("-", " ").strip() or "Video"


def _download_with_ytdlp(*, url: str, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(download_dir / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        out_template,
        url,
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaSourceError(
            "yt-dlp not found; install yt-dlp to download URLs (or pass a local video file path)"
        ) from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise MediaSourceError(detail or "yt-dlp download failed") from e

    # yt-dlp prints the final path on success in some versions; scan download_dir.
    del proc
    candidates = sorted(
        download_dir.glob("*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            return path.resolve()
    raise MediaSourceError("yt-dlp finished but no video file was found in download dir")
