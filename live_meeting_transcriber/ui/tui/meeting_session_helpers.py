"""Helpers for meeting list display (session type, labels)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.video_session_storage import (
    is_video_import_session,
    read_source_media_video_path,
    session_slides_dir,
)
from live_meeting_transcriber.audio.session_recording import session_audio_dir

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


def format_session_type_label(*, is_video: bool) -> str:
    """Short label for the meetings table Type column."""
    return "▶ Video" if is_video else "● Live"
