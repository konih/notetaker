"""Helpers for meeting list display (session type, labels)."""

from __future__ import annotations

from datetime import datetime, tzinfo
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.slide_review import format_timestamp
from live_meeting_transcriber.application.video_session_storage import (
    is_video_import_session,
    read_source_media_video_path,
    session_slides_dir,
)
from live_meeting_transcriber.audio.session_recording import session_audio_dir
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.utils.time import to_local

_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".m4v")


def session_is_video_import(data_dir: Path, session_id: UUID) -> bool:
    return is_video_import_session(data_dir.resolve(), session_id)


def session_has_slide_source(data_dir: Path, session_id: UUID) -> bool:
    """True when slide preview can run (import manifest and/or source video on disk)."""
    root = data_dir.resolve()
    if is_video_import_session(root, session_id):
        try:
            read_source_media_video_path(root, session_id)
            return True
        except Exception:
            return True
    session_dir = session_audio_dir(root, session_id)
    if session_dir.is_dir():
        for ext in _VIDEO_EXTENSIONS:
            if any(session_dir.glob(f"*{ext}")):
                return True
    return False


def count_saved_slides(data_dir: Path, session_id: UUID) -> int:
    slides_dir = session_slides_dir(data_dir.resolve(), session_id)
    if not slides_dir.is_dir():
        return 0
    return sum(1 for p in slides_dir.glob("*.png") if p.is_file())


def slide_preview_dir(data_dir: Path, session_id: UUID) -> Path:
    return (data_dir.resolve() / "imports" / "slide_previews" / str(session_id)).resolve()


def list_preview_candidate_timestamps(data_dir: Path, session_id: UUID) -> list[float]:
    """Timestamps from last slide preview run (PNG filenames under imports/slide_previews)."""
    preview = slide_preview_dir(data_dir, session_id)
    if not preview.is_dir():
        return []
    out: list[float] = []
    for path in sorted(preview.glob("candidate_*.png")):
        if not path.is_file():
            continue
        stem = path.stem  # candidate_000_12.5s
        if "_" not in stem:
            continue
        ts_part = stem.rsplit("_", 1)[-1]
        if not ts_part.endswith("s"):
            continue
        try:
            out.append(float(ts_part[:-1]))
        except ValueError:
            continue
    return out


def count_preview_candidates(data_dir: Path, session_id: UUID) -> int:
    return len(list_preview_candidate_timestamps(data_dir, session_id))


def format_slide_detail_note(
    *,
    saved_slides: int,
    preview_count: int,
    preview_timestamps: list[float],
    has_slide_source: bool,
) -> str:
    """Short slide status line for meeting detail header."""
    if saved_slides:
        return f" · [cyan]{saved_slides} slide(s) saved[/]"
    if preview_count:
        shown = preview_timestamps[:4]
        ts_text = ", ".join(format_timestamp(t) for t in shown)
        if preview_count > len(shown):
            ts_text += f", … (+{preview_count - len(shown)} more)"
        return f" · [cyan]{preview_count} slide(s) detected[/] ({ts_text}) · [dim]p[/] review · [bold]a[/] apply"
    if has_slide_source:
        return " · [dim]slide preview available ([/][bold]p[/][dim])[/]"
    return ""


def format_started_cell(started_at: datetime, now: datetime, tz: tzinfo | None = None) -> str:
    """Humanized Started cell for the meetings table.

    Recent meetings are what the operator scans for, so today/yesterday read as
    words with the wall-clock time; older rows keep the full sortable date.
    ``now`` is a parameter so tests own the clock.
    """
    local = to_local(started_at, tz)
    local_now = to_local(now, tz)
    if local.date() == local_now.date():
        return f"today {local:%H:%M}"
    if (local_now.date() - local.date()).days == 1:
        return f"yesterday {local:%H:%M}"
    return f"{local:%Y-%m-%d %H:%M}"


def meeting_row_cells(
    session: MeetingSession,
    *,
    is_video: bool,
    active_session_id: UUID | None,
    now: datetime,
    tz: tzinfo | None = None,
    max_title: int = 24,
) -> tuple[str, str, str, str]:
    """``(glyph, glyph_style, title, started)`` for one meetings-table row.

    The session's state lives in a one-cell glyph column — ● live recording,
    ▶ video import, ⏸ *interrupted* — so the title column stays scannable and
    the Started column actually fits the table (the old ``⏸ interrupted ·``
    title prefix pushed it out of view).

    A meeting whose recording was interrupted (app crash / force-quit) never
    got ``ended_at`` set, so it is stuck all-"unknown" until re-diarized. Flag
    it so the operator can find it and run Speaker ID (Ctrl+D) — but never
    flag the session that is actively recording right now.
    """
    if session.ended_at is None and session.id != active_session_id:
        glyph, style = "⏸", "yellow"
    elif is_video:
        glyph, style = "▶", "cyan"
    else:
        glyph, style = "●", "green"
    title = session.title[:max_title] + ("…" if len(session.title) > max_title else "")
    return glyph, style, title, format_started_cell(session.started_at, now, tz)
