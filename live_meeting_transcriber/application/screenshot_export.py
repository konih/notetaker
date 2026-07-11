"""Match GNOME-style screenshot files to meeting time ranges and prepare export assets."""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.session_audio import (
    live_captures_dir,
    live_captures_manifest_path,
    session_audio_dir,
)
from live_meeting_transcriber.utils.time import ensure_aware

# e.g. "Screenshot From 2026-05-11 09-24-01.png" / "Screenshot from 2026-05-11 09-24-01 (1).png"
_SCREENSHOT_NAME_RE = re.compile(
    r"^screenshot\s+from\s+(\d{4}-\d{2}-\d{2})\s+(\d{2})-(\d{2})-(\d{2})(?:\s*\(\d+\))?\.(png|jpe?g)$",
    re.IGNORECASE,
)

# macOS default names, e.g. "Screenshot 2026-05-11 at 9.24.01 AM.png" (12h) or
# "Screenshot 2026-05-11 at 14.24.01.png" (24h locale). Colons are illegal in HFS
# filenames so the time uses '.' separators, and recent macOS inserts a narrow
# no-break space (U+202F) before AM/PM — matched via the explicit whitespace class.
_MACOS_SCREENSHOT_NAME_RE = re.compile(
    r"^screenshot\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d{1,2})\.(\d{2})\.(\d{2})"
    r"(?:[\s\u00a0\u202f]*(am|pm))?(?:\s*\(\d+\))?\.(png|jpe?g)$",
    re.IGNORECASE,
)


def parse_gnome_screenshot_filename(name: str) -> datetime | None:
    """Parse wall-clock time from a GNOME Screenshots-style filename; returns naive local datetime."""
    m = _SCREENSHOT_NAME_RE.match(name.strip())
    if not m:
        return None
    date_part = m.group(1)
    y, mo, d = int(date_part[0:4]), int(date_part[5:7]), int(date_part[8:10])
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def parse_macos_screenshot_filename(name: str) -> datetime | None:
    """Parse wall-clock time from a macOS Screenshot filename; returns naive local datetime."""
    m = _MACOS_SCREENSHOT_NAME_RE.match(name.strip())
    if not m:
        return None
    date_part = m.group(1)
    y, mo, d = int(date_part[0:4]), int(date_part[5:7]), int(date_part[8:10])
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
    meridiem = m.group(5)
    if meridiem is not None:
        m_lower = meridiem.lower()
        if m_lower == "am" and h == 12:  # 12 AM -> 00:xx
            h = 0
        elif m_lower == "pm" and h != 12:  # 1-11 PM -> 13-23; 12 PM stays 12
            h += 12
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def parse_screenshot_filename(name: str) -> datetime | None:
    """Parse a screenshot filename in either GNOME or macOS style; ``None`` if neither matches."""
    return parse_gnome_screenshot_filename(name) or parse_macos_screenshot_filename(name)


def local_naive_to_utc_naive(naive_local: datetime) -> datetime:
    """Interpret naive datetime as local machine time; return UTC naive (matches stored session times)."""
    secs = time.mktime(naive_local.timetuple())
    return datetime.fromtimestamp(secs, tz=UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ScreenshotHit:
    """One screenshot file whose capture time falls inside the session window (UTC naive)."""

    captured_utc: datetime
    source_path: Path


def _session_time_bounds(
    session: MeetingSession, segments: list[TranscriptSegment]
) -> tuple[datetime, datetime]:
    start = session.started_at
    end = session.ended_at
    if end is None and segments:
        end = max(s.ended_at for s in segments)
    if end is None:
        end = start
    return start, end


def slide_captured_utc_from_manifest_item(
    session: MeetingSession,
    item: dict[str, object],
) -> datetime | None:
    """Map a slides.json row to session wall time (video seconds + session.started_at)."""
    ts_raw = item.get("timestamp_seconds")
    if isinstance(ts_raw, (int, float)):
        return session.started_at + timedelta(seconds=float(ts_raw))
    captured_raw = item.get("captured_at")
    if isinstance(captured_raw, str):
        try:
            return datetime.fromisoformat(captured_raw)
        except ValueError:
            return None
    return None


def list_session_video_slides(
    data_dir: Path,
    session: MeetingSession,
) -> list[ScreenshotHit]:
    """Load slide PNGs saved by ``transcribe-video`` (``sessions/<id>/slides/slides.json``)."""
    manifest_path = session_audio_dir(data_dir, session.id) / "slides" / "slides.json"
    if not manifest_path.is_file():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    slides_dir = manifest_path.parent
    hits: list[ScreenshotHit] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path_name = item.get("path")
        if not isinstance(path_name, str):
            continue
        img = slides_dir / path_name
        if not img.is_file():
            continue
        captured = slide_captured_utc_from_manifest_item(session, item)
        if captured is None:
            continue
        hits.append(ScreenshotHit(captured_utc=captured, source_path=img.resolve()))
    hits.sort(key=lambda h: (h.captured_utc, str(h.source_path)))
    return hits


def list_session_live_captures(
    data_dir: Path,
    session: MeetingSession,
) -> list[ScreenshotHit]:
    """Load live screen captures journaled by the F6 loop (``screenshots/captures.json``).

    Timestamps are stored ISO-UTC by the loop and coerced tz-aware here so they compare
    cleanly with DB-backed session/segment times (A11).
    """
    root = session_audio_dir(data_dir, session.id)
    manifest_path = live_captures_manifest_path(root)
    if not manifest_path.is_file():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    captures = live_captures_dir(root)
    hits: list[ScreenshotHit] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path_name = item.get("path")
        captured_raw = item.get("captured_at")
        if not isinstance(path_name, str) or not isinstance(captured_raw, str):
            continue
        img = captures / path_name
        if not img.is_file():
            continue
        try:
            captured = ensure_aware(datetime.fromisoformat(captured_raw))
        except ValueError:
            continue
        hits.append(ScreenshotHit(captured_utc=captured, source_path=img.resolve()))
    hits.sort(key=lambda h: (h.captured_utc, str(h.source_path)))
    return hits


def list_session_screenshots(
    source_dir: Path | None,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    *,
    data_dir: Path | None = None,
) -> list[ScreenshotHit]:
    """Find GNOME/macOS screenshots in ``source_dir`` and/or video slides under ``data_dir``."""
    hits: list[ScreenshotHit] = []
    if source_dir is not None and source_dir.is_dir():
        t0, t1 = _session_time_bounds(session, segments)
        for path in sorted(source_dir.iterdir()):
            if not path.is_file():
                continue
            local_naive = parse_screenshot_filename(path.name)
            if local_naive is None:
                continue
            utc_naive = local_naive_to_utc_naive(local_naive)
            if t0 <= utc_naive <= t1:
                hits.append(ScreenshotHit(captured_utc=utc_naive, source_path=path.resolve()))
        hits.sort(key=lambda h: (h.captured_utc, str(h.source_path)))

    if data_dir is not None:
        seen = {h.source_path for h in hits}
        for h in (
            *list_session_video_slides(data_dir, session),
            *list_session_live_captures(data_dir, session),
        ):
            if h.source_path not in seen:
                hits.append(h)
                seen.add(h.source_path)
        hits.sort(key=lambda h: (h.captured_utc, str(h.source_path)))
    return hits


def _normalized_image_suffix(src: Path) -> str:
    ext = (src.suffix or ".png").lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in (".png", ".jpg", ".webp"):
        ext = ".png"
    return ext


def export_screenshot_basename(
    session_id: UUID,
    src: Path,
    captured_utc: datetime,
    index: int,
) -> str:
    """Deterministic, Obsidian-friendly name (re-export overwrites the same path).

    Includes a short session id so a shared Obsidian Screenshots folder does not collide
    across meetings. ``index`` is the 0-based position in the session's sorted list.
    """
    ext = _normalized_image_suffix(src)
    ts = captured_utc.strftime("%Y%m%dT%H%M%S")
    sid = str(session_id).replace("-", "")[:8]
    return f"screenshot_{sid}_{ts}_{index:03d}{ext}"


def copy_screenshot_for_export(
    src: Path,
    dest_dir: Path,
    *,
    session_id: UUID,
    captured_utc: datetime,
    index: int,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = export_screenshot_basename(session_id, src, captured_utc, index)
    dest = dest_dir / base
    shutil.copy2(src, dest)
    return dest.resolve()


def markdown_image_line(*, alt: str, relative_link: str) -> str:
    return f"  - ![{alt}]({relative_link})"


def merge_transcript_lines_with_screenshots(
    segments: list[TranscriptSegment],
    speaker_line_fn: Callable[[TranscriptSegment], str],
    screenshot_md_fn: Callable[[ScreenshotHit], str],
    *,
    session: MeetingSession,
    shots: list[ScreenshotHit],
) -> list[str]:
    """Place screenshots after the transcript line for the segment that contains their capture time."""
    segs = sorted(segments, key=lambda s: s.started_at)
    lines: list[str] = []
    used_paths: set[Path] = set()

    if not segs:
        for h in shots:
            lines.append(screenshot_md_fn(h))
        return lines

    # Before first segment (still in session)
    first_lo = segs[0].started_at
    for h in shots:
        if h.captured_utc < first_lo:
            lines.append(screenshot_md_fn(h))
            used_paths.add(h.source_path)

    for seg in segs:
        lines.append(speaker_line_fn(seg))
        lo, hi = seg.started_at, seg.ended_at
        for h in shots:
            if h.source_path in used_paths:
                continue
            if lo <= h.captured_utc <= hi:
                lines.append(screenshot_md_fn(h))
                used_paths.add(h.source_path)

    t_end = session.ended_at or (segs[-1].ended_at if segs else session.started_at)
    last_hi = segs[-1].ended_at
    for h in shots:
        if h.source_path in used_paths:
            continue
        if last_hi < h.captured_utc <= t_end:
            lines.append(screenshot_md_fn(h))
            used_paths.add(h.source_path)

    return lines
