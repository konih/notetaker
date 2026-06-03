"""Unit tests for TUI slide preview helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.ui.tui.slide_preview_helpers import (
    accepted_candidates,
    build_slide_params,
    format_candidate_label,
    normalize_strategy,
    open_image_externally,
)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_build_slide_params_uses_settings_defaults_for_empty_fields() -> None:
    s = _settings(
        video_slide_sample_interval_seconds=3.0,
        video_slide_change_threshold=0.2,
        video_slide_min_interval_seconds=10.0,
        video_slide_max_candidates=50,
    )
    params = build_slide_params(
        sample_interval="",
        threshold="",
        min_interval="",
        max_candidates="",
        settings=s,
    )
    assert params.sample_interval_seconds == 3.0
    assert params.change_threshold == 0.2
    assert params.min_slide_interval_seconds == 10.0
    assert params.max_candidates == 50


def test_build_slide_params_parses_overrides() -> None:
    s = _settings()
    params = build_slide_params(
        sample_interval="1.5",
        threshold="0.25",
        min_interval="20",
        max_candidates="80",
        settings=s,
    )
    assert params == SlideDetectionParams(
        sample_interval_seconds=1.5,
        change_threshold=0.25,
        min_slide_interval_seconds=20.0,
        max_candidates=80,
    )


def test_normalize_strategy_falls_back_to_settings() -> None:
    s = _settings(video_slide_strategy="ffmpeg_scene")
    assert normalize_strategy("", settings=s) == "ffmpeg_scene"
    assert normalize_strategy("frame_diff", settings=s) == "frame_diff"


def test_format_candidate_label_marks_review_state() -> None:
    cand = SlideCandidate(timestamp_seconds=65.0, change_score=0.33, preview_path=None)
    assert "1:05" in format_candidate_label(0, cand, keep=None)
    assert "[✓]" in format_candidate_label(0, cand, keep=True)
    assert "[✗]" in format_candidate_label(0, cand, keep=False)


def test_accepted_candidates_filters_kept_rows() -> None:
    cands = [
        SlideCandidate(timestamp_seconds=1.0, change_score=0.1),
        SlideCandidate(timestamp_seconds=2.0, change_score=0.2),
        SlideCandidate(timestamp_seconds=3.0, change_score=0.3),
    ]
    review = {0: True, 1: False, 2: True}
    accepted = accepted_candidates(cands, review)
    assert accepted == [cands[0], cands[2]]


def test_open_image_externally_no_file(tmp_path: Path) -> None:
    assert open_image_externally(tmp_path / "missing.png") is False


def test_open_image_externally_launches_viewer(tmp_path: Path) -> None:
    png = tmp_path / "slide.png"
    png.write_bytes(b"png")
    with (
        patch(
            "live_meeting_transcriber.ui.tui.slide_preview_helpers.shutil.which",
            return_value="/usr/bin/xdg-open",
        ),
        patch("live_meeting_transcriber.ui.tui.slide_preview_helpers.subprocess.Popen") as popen,
    ):
        assert open_image_externally(png) is True
        popen.assert_called_once()
        assert popen.call_args.args[0] == ["/usr/bin/xdg-open", str(png.resolve())]


def test_build_slide_params_invalid_raises() -> None:
    s = _settings()
    with pytest.raises(ValueError):
        build_slide_params(
            sample_interval="not-a-number",
            threshold="0.1",
            min_interval="1",
            max_candidates="10",
            settings=s,
        )
