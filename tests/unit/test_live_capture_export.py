"""F6 — live captures interleave into exports like slides/screenshots do."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from live_meeting_transcriber.application.screenshot_export import (
    list_session_live_captures,
    list_session_screenshots,
)
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.domain.session_audio import (
    live_captures_dir,
    live_captures_manifest_path,
    session_audio_dir,
)


def _session() -> MeetingSession:
    return MeetingSession(
        title="t",
        started_at=datetime(2026, 7, 11, 9, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 7, 11, 10, 0, 0, tzinfo=UTC),
    )


def _write_capture(root: Path, name: str, captured_at: str) -> None:
    captures = live_captures_dir(root)
    captures.mkdir(parents=True, exist_ok=True)
    (captures / name).write_bytes(b"\x89PNG fake")
    manifest_path = live_captures_manifest_path(root)
    items = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    items.append({"path": name, "captured_at": captured_at})
    manifest_path.write_text(json.dumps(items))


def test_live_captures_listed_with_aware_utc_timestamps(tmp_path: Path) -> None:
    session = _session()
    root = session_audio_dir(tmp_path, session.id)
    _write_capture(root, "capture_20260711T091500Z_000.png", "2026-07-11T09:15:00+00:00")
    _write_capture(root, "capture_20260711T093000Z_001.png", "2026-07-11T09:30:00+00:00")

    hits = list_session_live_captures(tmp_path, session)
    assert [h.source_path.name for h in hits] == [
        "capture_20260711T091500Z_000.png",
        "capture_20260711T093000Z_001.png",
    ]
    assert all(h.captured_utc.tzinfo is not None for h in hits)


def test_missing_or_corrupt_manifest_yields_no_hits(tmp_path: Path) -> None:
    session = _session()
    assert list_session_live_captures(tmp_path, session) == []
    root = session_audio_dir(tmp_path, session.id)
    live_captures_dir(root).mkdir(parents=True, exist_ok=True)
    live_captures_manifest_path(root).write_text("{not json")
    assert list_session_live_captures(tmp_path, session) == []


def test_manifest_entry_with_missing_file_is_skipped(tmp_path: Path) -> None:
    session = _session()
    root = session_audio_dir(tmp_path, session.id)
    _write_capture(root, "capture_a.png", "2026-07-11T09:15:00+00:00")
    manifest_path = live_captures_manifest_path(root)
    items = json.loads(manifest_path.read_text())
    items.append({"path": "capture_gone.png", "captured_at": "2026-07-11T09:20:00+00:00"})
    manifest_path.write_text(json.dumps(items))

    hits = list_session_live_captures(tmp_path, session)
    assert [h.source_path.name for h in hits] == ["capture_a.png"]


def test_session_screenshots_include_live_captures(tmp_path: Path) -> None:
    session = _session()
    root = session_audio_dir(tmp_path, session.id)
    _write_capture(root, "capture_20260711T091500Z_000.png", "2026-07-11T09:15:00+00:00")

    hits = list_session_screenshots(None, session, [], data_dir=tmp_path)
    assert [h.source_path.name for h in hits] == ["capture_20260711T091500Z_000.png"]
