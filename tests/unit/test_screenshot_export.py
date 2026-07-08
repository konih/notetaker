from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from live_meeting_transcriber.application.screenshot_export import (
    export_screenshot_basename,
    list_session_screenshots,
    list_session_video_slides,
    merge_transcript_lines_with_screenshots,
    parse_gnome_screenshot_filename,
    slide_captured_utc_from_manifest_item,
)
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.obsidian.meeting_export import write_dual_export


def test_export_screenshot_basename_deterministic_index(tmp_path: Path) -> None:
    src = tmp_path / "Screenshot From 2026-05-11 10-05-00 (1).png"
    src.write_bytes(b"x")
    cap = datetime(2026, 5, 11, 10, 5, 0)
    sid = UUID("7aef9cf1-e33c-4598-816f-0c61a8be164f")
    assert (
        export_screenshot_basename(sid, src, cap, 0)
        == "screenshot_7aef9cf1_20260511T100500_000.png"
    )
    assert (
        export_screenshot_basename(sid, src, cap, 12)
        == "screenshot_7aef9cf1_20260511T100500_012.png"
    )
    assert " " not in export_screenshot_basename(sid, src, cap, 0)


def test_parse_gnome_screenshot_filename() -> None:
    d = parse_gnome_screenshot_filename("Screenshot From 2026-05-11 09-24-01.png")
    assert d == datetime(2026, 5, 11, 9, 24, 1)
    d2 = parse_gnome_screenshot_filename("Screenshot from 2026-05-11 09-24-01 (1).png")
    assert d2 == datetime(2026, 5, 11, 9, 24, 1)
    assert parse_gnome_screenshot_filename("other.png") is None


def test_list_session_screenshots_respects_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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


def test_write_dual_export_copies_screenshots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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

    result = write_dual_export(
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
    app_path = result.app_path
    obs_path = result.obs_path
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


def test_list_session_video_slides_from_manifest(tmp_path: Path) -> None:
    sid = uuid4()
    session = MeetingSession(id=sid, title="Talk", started_at=datetime(2026, 6, 3, 10, 0, 0))
    slides_dir = tmp_path / "sessions" / str(sid) / "slides"
    slides_dir.mkdir(parents=True)
    img = slides_dir / "slide_000_0.0s.png"
    img.write_bytes(b"png")
    cap = datetime(2026, 6, 3, 10, 0, 0)
    (slides_dir / "slides.json").write_text(
        '[{"index": 0, "timestamp_seconds": 0.0, "captured_at": "2026-06-03T10:00:00", '
        '"path": "slide_000_0.0s.png", "change_score": 1.0}]',
        encoding="utf-8",
    )
    hits = list_session_video_slides(tmp_path, session)
    assert len(hits) == 1
    assert hits[0].source_path == img.resolve()
    assert hits[0].captured_utc == cap


def test_slide_captured_utc_prefers_timestamp_seconds() -> None:
    session = MeetingSession(
        id=uuid4(),
        title="Talk",
        started_at=datetime(2026, 6, 3, 10, 0, 0),
    )
    captured = slide_captured_utc_from_manifest_item(
        session,
        {
            "timestamp_seconds": 45.0,
            "captured_at": "2000-01-01T00:00:00",
            "path": "slide.png",
        },
    )
    assert captured == session.started_at + timedelta(seconds=45.0)


def test_list_session_screenshots_loads_video_slides_without_gnome_dir(tmp_path: Path) -> None:
    sid = uuid4()
    t0 = datetime(2026, 6, 3, 10, 0, 0)
    session = MeetingSession(
        id=sid, title="Video", started_at=t0, ended_at=t0 + timedelta(minutes=5)
    )
    slides_dir = tmp_path / "sessions" / str(sid) / "slides"
    slides_dir.mkdir(parents=True)
    img = slides_dir / "slide_000_30.0s.png"
    img.write_bytes(b"png")
    (slides_dir / "slides.json").write_text(
        '[{"index": 0, "timestamp_seconds": 30.0, "path": "slide_000_30.0s.png", '
        '"change_score": 1.0}]',
        encoding="utf-8",
    )
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=2),
        text="intro",
    )
    seg2 = TranscriptSegment(
        session_id=sid,
        started_at=t0 + timedelta(minutes=2),
        ended_at=t0 + timedelta(minutes=5),
        text="body",
    )
    hits = list_session_screenshots(None, session, [seg, seg2], data_dir=tmp_path)
    assert len(hits) == 1
    assert hits[0].captured_utc == t0 + timedelta(seconds=30.0)


def test_merge_video_slide_at_timestamp_not_end_of_export(tmp_path: Path) -> None:
    sid = uuid4()
    t0 = datetime(2026, 6, 3, 10, 0, 0)
    session = MeetingSession(
        id=sid, title="Video", started_at=t0, ended_at=t0 + timedelta(minutes=5)
    )
    s1 = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=2),
        text="intro",
    )
    s2 = TranscriptSegment(
        session_id=sid,
        started_at=t0 + timedelta(minutes=2),
        ended_at=t0 + timedelta(minutes=5),
        text="body",
    )
    from live_meeting_transcriber.application.screenshot_export import ScreenshotHit

    slide_path = tmp_path / "slide.png"
    slide_path.write_bytes(b"x")
    hits = [ScreenshotHit(captured_utc=t0 + timedelta(seconds=30.0), source_path=slide_path)]

    lines = merge_transcript_lines_with_screenshots(
        [s1, s2],
        lambda seg: f"LINE:{seg.text}",
        lambda h: f"IMG:{h.source_path.name}",
        session=session,
        shots=hits,
    )
    assert lines == ["LINE:intro", "IMG:slide.png", "LINE:body"]


def test_write_dual_export_includes_video_slides_without_screenshots_dir(
    tmp_path: Path,
) -> None:
    sid = uuid4()
    t0 = datetime(2026, 6, 3, 10, 0, 0)
    session = MeetingSession(
        id=sid, title="Video", started_at=t0, ended_at=t0 + timedelta(minutes=5)
    )
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(minutes=5),
        text="hello",
    )
    slides_dir = tmp_path / "app" / "sessions" / str(sid) / "slides"
    slides_dir.mkdir(parents=True)
    (slides_dir / "slide_000_30.0s.png").write_bytes(b"png")
    (slides_dir / "slides.json").write_text(
        '[{"index": 0, "timestamp_seconds": 30.0, "path": "slide_000_30.0s.png", '
        '"change_score": 1.0}]',
        encoding="utf-8",
    )

    result = write_dual_export(
        app_base_dir=tmp_path / "app",
        session=session,
        segments=[seg],
        summary=None,
        speaker_display=None,
        obsidian_meetings_dir=None,
        obsidian_meeting_template=None,
        screenshots_source_dir=None,
    )
    text = result.app_path.read_text(encoding="utf-8")
    assert "hello" in text
    assert "slide_000_30.0s.png" in text or "screenshot_" in text
    hello_idx = text.index("hello")
    img_idx = text.index(".png")
    assert img_idx > hello_idx
