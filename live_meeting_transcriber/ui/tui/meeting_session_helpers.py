"""Helpers for meeting list display (session type, labels)."""

from __future__ import annotations

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


def format_session_type_label(*, is_video: bool) -> str:
    """Short label for the meetings table Type column."""
    return "▶ Video" if is_video else "● Live"


def format_meeting_row_title(
    session: MeetingSession, *, active_session_id: UUID | None = None, max_len: int = 40
) -> str:
    """Title for the meetings table, marking *interrupted* meetings.

    A meeting whose recording was interrupted (app crash / force-quit) never got ``ended_at`` set,
    so it is stuck all-"unknown" until re-diarized. Flag it so the operator can find it and run
    Speaker ID (Ctrl+D) — but never flag the session that is actively recording right now.
    """
    title = session.title
    truncated = title[:max_len] + ("…" if len(title) > max_len else "")
    if session.ended_at is None and session.id != active_session_id:
        return f"⏸ interrupted · {truncated}"
    return truncated
