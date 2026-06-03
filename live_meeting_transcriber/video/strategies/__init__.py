"""Pluggable slide detection strategies."""

from live_meeting_transcriber.video.strategies.factory import build_slide_strategy

__all__ = ["build_slide_strategy"]
