from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from live_meeting_transcriber.application.screenshot_export import (
    export_screenshot_basename,
    list_session_screenshots,
    merge_transcript_lines_with_screenshots,
    parse_gnome_screenshot_filename,
)
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.obsidian.meeting_export import write_dual_export


def test_export_screenshot_basename_deterministic_index(tmp_path: Path) -> None:
    src = tmp_path / "Screenshot From 2026-05-11 10-05-00 (1).png"
    src.write_bytes(b"x")
    cap = datetime(2026, 5, 11, 10, 5, 0)
    sid = UUID("7aef9cf1-e33c-4598-816f-0c61a8be164f")
    assert (
        export_screenshot_basename(sid, src, cap, 0) == "screenshot_7aef9cf1_20260511T100500_000.png"
    )
    assert (
        export_screenshot_basename(sid, src, cap, 12) == "screenshot_7aef9cf1_20260511T100500_012.png"
    )
    assert " " not in export_screenshot_basename(sid, src, cap, 0)


def test_parse_gnome_screenshot_filename() -> None:
    d = parse_gnome_screenshot_filename("Screenshot From 2026-05-11 09-24-01.png")
    assert d == datetime(2026, 5, 11, 9, 24, 1)
    d2 = parse_gnome_screenshot_filename("Screenshot from 2026-05-11 09-24-01 (1).png")
    assert d2 == datetime(2026, 5, 11, 9, 24, 1)
    assert parse_gnome_screenshot_filename("other.png") is None


def test_list_session_screenshots_respects_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "live_meeting_transcriber.application.screenshot_export.local_naive_to_utc_naive",
        lambda dt: dt,
    )
    shot_dir = tmp_path / "shots"
    shot_dir.mkdir()
    (shot_dir / "Screenshot from 2026-05-11 10-45-00.png").write_bytes(b"x")
    (shot_dir / "Screenshot from 2026-05-11 12-00-00.png").write_bytes(b"x")
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 10, 30, 0)
    t1 = datetime(2026, 5, 11, 11, 30, 0)
    session = MeetingSession(id=sid, title="M", started_at=t0, ended_at=t1)
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=30),
        text="a",
    )
    hits = list_session_screenshots(shot_dir, session, [seg])
    assert len(hits) == 1
    assert "10-45-00" in hits[0].source_path.name


def test_merge_inserts_screenshot_after_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "live_meeting_transcriber.application.screenshot_export.local_naive_to_utc_naive",
        lambda dt: dt,
    )
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 10, 0, 0)
    session = MeetingSession(id=sid, title="M", started_at=t0, ended_at=t0 + timedelta(hours=1))
    s1 = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=10),
        text="one",
    )
    s2 = TranscriptSegment(
        session_id=sid,
        started_at=t0 + timedelta(minutes=10),
        ended_at=t0 + timedelta(minutes=20),
        text="two",
    )
    from live_meeting_transcriber.application.screenshot_export import ScreenshotHit

    hits = [
        ScreenshotHit(captured_utc=t0 + timedelta(minutes=5), source_path=Path("/tmp/a.png")),
    ]

    lines = merge_transcript_lines_with_screenshots(
        [s1, s2],
        lambda seg: f"LINE:{seg.text}",
        lambda h: f"IMG:{h.source_path.name}",
        session=session,
        shots=hits,
    )
    assert lines == ["LINE:one", "IMG:a.png", "LINE:two"]


def test_write_dual_export_copies_screenshots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "live_meeting_transcriber.application.screenshot_export.local_naive_to_utc_naive",
        lambda dt: dt,
    )
    shot_dir = tmp_path / "shots"
    shot_dir.mkdir()
    png = shot_dir / "Screenshot from 2026-05-11 10-05-00.png"
    png.write_bytes(b"fakepng")

    vault = tmp_path / "vault"
    meetings = vault / "Meetings"
    meetings.mkdir(parents=True)
    tpl = vault / "Templates" / "Meeting.md"
    tpl.parent.mkdir(parents=True)
    tpl.write_text(
        "## Notes\n\n## Decisions\n\n## Action items\n\n## Meeting Transcript\n",
        encoding="utf-8",
    )

    sid = uuid4()
    t0 = datetime(2026, 5, 11, 10, 0, 0)
    session = MeetingSession(id=sid, title="Meet", started_at=t0, ended_at=t0 + timedelta(hours=1))
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=10),
        text="hello",
    )

    app_path, obs_path = write_dual_export(
        app_base_dir=tmp_path / "app",
        session=session,
        segments=[seg],
        summary=None,
        speaker_display=None,
        obsidian_meetings_dir=meetings,
        obsidian_meeting_template=tpl,
        screenshots_source_dir=shot_dir,
        obsidian_screenshots_dir=vault / "Images" / "Screenshots",
    )
    text = app_path.read_text(encoding="utf-8")
    assert "hello" in text
    assert "screenshots" in text
    assert ".png" in text
    assert obs_path is not None
    obs_text = obs_path.read_text(encoding="utf-8")
    assert "hello" in obs_text
    imgs = vault / "Images" / "Screenshots"
    assert imgs.is_dir()
    exported = list(imgs.iterdir())
    assert any(p.suffix == ".png" for p in exported)
    for p in exported:
        assert " " not in p.name
        assert re.fullmatch(r"[a-zA-Z0-9_.-]+", p.name)
        assert p.name.startswith("screenshot_")
