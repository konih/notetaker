"""Helpers for meeting list display (session type, labels)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.video_session_storage import is_video_import_session


def session_is_video_import(data_dir: Path, session_id: UUID) -> bool:
    return is_video_import_session(data_dir.resolve(), session_id)


def format_session_type_label(*, is_video: bool) -> str:
    """Short label for the meetings table Type column."""
    return "▶ Video" if is_video else "● Live"
