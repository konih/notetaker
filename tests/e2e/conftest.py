"""Shared e2e fixtures (T4): generated sample media for the video/slides smokes."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.video_helpers import ffmpeg_available, generate_sample_video


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A locally generated 3-slide presentation MP4 (requires the ffmpeg binary)."""
    if not ffmpeg_available():
        pytest.skip("requires the ffmpeg binary (real video encode/probe)")
    dest = tmp_path / "sample_presentation.mp4"
    return generate_sample_video(dest, slide_seconds=15.0)
