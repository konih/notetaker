from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from live_meeting_transcriber.domain.models import SlideDetectionParams
from live_meeting_transcriber.video.slide_common import effective_min_slide_interval
from live_meeting_transcriber.video.slide_detection import detect_slide_candidates
from live_meeting_transcriber.video.strategies.factory import build_slide_strategy
from live_meeting_transcriber.video.strategies.ffmpeg_scene import FfmpegSceneStrategy
from tests.fixtures.paths import PRESENTATION_EN_VIDEO


def test_effective_min_slide_interval_caps_short_clips() -> None:
    assert effective_min_slide_interval(15.0, 15.0) == 5.0
    assert effective_min_slide_interval(15.0, 45.0) == 15.0
    assert effective_min_slide_interval(0.0, 15.0) == 0.0


def test_ffmpeg_scene_probe_flushes_multiple_timestamps() -> None:
    fake_stderr = """
[Parsed_showinfo_1 @ 0x0] n:   0 pts: 104093 pts_time:3.469767
[Parsed_showinfo_1 @ 0x0] n:   1 pts: 396385 pts_time:13.212833
"""
    strategy = FfmpegSceneStrategy()
    with patch(
        "live_meeting_transcriber.video.strategies.ffmpeg_scene.subprocess.run",
        return_value=type("R", (), {"returncode": 0, "stdout": "", "stderr": fake_stderr})(),
    ):
        raw = strategy._probe_scene_timestamps(video_path=Path("x.mp4"), threshold=0.12)
    assert [round(ts, 1) for ts, _ in raw] == [3.5, 13.2]


def test_detect_slide_candidates_respects_min_interval(tmp_path: Path) -> None:
    video = tmp_path / "fake.mp4"
    video.write_bytes(b"x")

    frames = [
        b"\x00" * 100,
        b"\xff" * 100,
        b"\x00" * 100,
    ]
    call_count = {"n": 0}

    def fake_extract(**kwargs) -> bytes:  # type: ignore[no-untyped-def]
        idx = call_count["n"]
        call_count["n"] += 1
        if idx >= len(frames):
            return frames[-1]
        return frames[idx]

    with patch(
        "live_meeting_transcriber.video.strategies.frame_diff.extract_gray_frame_bytes",
        side_effect=fake_extract,
    ):
        cands = detect_slide_candidates(
            video_path=video,
            duration_seconds=60.0,
            sample_interval_seconds=2.0,
            change_threshold=0.1,
            min_slide_interval_seconds=3.0,
            max_candidates=10,
            preview_dir=None,
        )

    assert len(cands) == 2
    assert cands[0].timestamp_seconds == 0.0
    assert cands[1].timestamp_seconds == 4.0


@pytest.mark.skipif(not PRESENTATION_EN_VIDEO.is_file(), reason="presentation fixture missing")
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")
def test_presentation_en_fixture_default_params_find_multiple_slides() -> None:
    params = SlideDetectionParams(
        sample_interval_seconds=2.0,
        change_threshold=0.12,
        min_slide_interval_seconds=15.0,
        max_candidates=120,
    )
    for strategy_name in ("frame_diff", "ffmpeg_scene"):
        cands = build_slide_strategy(strategy_name).detect(
            video_path=PRESENTATION_EN_VIDEO,
            duration_seconds=15.048,
            params=params,
        )
        assert len(cands) >= 2, strategy_name


def test_detect_slide_candidates_max_cap(tmp_path: Path) -> None:
    video = tmp_path / "fake.mp4"
    video.write_bytes(b"x")

    toggle = {"i": 0}

    def alternating(**kwargs) -> bytes:  # type: ignore[no-untyped-def]
        toggle["i"] += 1
        return b"\x00" * 50 if toggle["i"] % 2 else b"\xff" * 50

    with patch(
        "live_meeting_transcriber.video.strategies.frame_diff.extract_gray_frame_bytes",
        side_effect=alternating,
    ):
        cands = detect_slide_candidates(
            video_path=video,
            duration_seconds=100.0,
            sample_interval_seconds=1.0,
            change_threshold=0.1,
            min_slide_interval_seconds=0.0,
            max_candidates=3,
            preview_dir=None,
        )

    assert len(cands) == 3


def test_build_slide_strategy_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown slide strategy"):
        build_slide_strategy("histogram")
