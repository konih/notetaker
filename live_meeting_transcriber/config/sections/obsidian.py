"""Obsidian vault + OS screenshot export settings."""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def _expanded_path(v: object) -> Path | None:
    if v is None or v == "":
        return None
    return Path(str(v)).expanduser().resolve()


class ObsidianSettings(BaseSettings):
    """Optional vault integration: people autocomplete + meeting template export."""

    obsidian_people_dir: Path | None = Field(default=None, alias="OBSIDIAN_PEOPLE_DIR")
    obsidian_meetings_dir: Path | None = Field(default=None, alias="OBSIDIAN_MEETINGS_DIR")
    obsidian_meeting_template: Path | None = Field(default=None, alias="OBSIDIAN_MEETING_TEMPLATE")
    obsidian_person_template: Path | None = Field(default=None, alias="OBSIDIAN_PERSON_TEMPLATE")
    obsidian_screenshots_dir: Path | None = Field(default=None, alias="OBSIDIAN_SCREENSHOTS_DIR")

    @field_validator(
        "obsidian_people_dir",
        "obsidian_meetings_dir",
        "obsidian_meeting_template",
        "obsidian_person_template",
        "obsidian_screenshots_dir",
        mode="before",
    )
    @classmethod
    def _obsidian_paths(cls, v: object) -> Path | None:
        return _expanded_path(v)

    def effective_obsidian_screenshots_dir(self) -> Path | None:
        """Where to copy screenshots for Obsidian embeds; defaults next to Meetings folder."""
        if self.obsidian_screenshots_dir is not None:
            return self.obsidian_screenshots_dir
        if self.obsidian_meetings_dir is not None:
            return (self.obsidian_meetings_dir.parent / "Images" / "Screenshots").resolve()
        return None


class ScreenshotSettings(BaseSettings):
    """GNOME-style screenshots (filename timestamps matched to session UTC bounds)."""

    screenshots_export_enabled: bool = Field(default=True, alias="SCREENSHOTS_EXPORT_ENABLED")
    screenshots_source_dir: Path | None = Field(default=None, alias="SCREENSHOTS_SOURCE_DIR")
    # Live screen capture during recording (F6). Capturing the screen is invasive, so
    # this is privacy-default-OFF; when enabled, periodic captures land under the
    # session directory (``sessions/<id>/screenshots/``) and are interleaved into
    # markdown exports as visual who-was-speaking context. macOS ``screencapture``
    # needs the Screen Recording (TCC) permission — see docs/configuration.md.
    live_screen_capture_enabled: bool = Field(default=False, alias="LIVE_SCREEN_CAPTURE_ENABLED")
    live_screen_capture_interval_seconds: int = Field(
        default=60, alias="LIVE_SCREEN_CAPTURE_INTERVAL_SECONDS", ge=5, le=3600
    )

    @field_validator("screenshots_source_dir", mode="before")
    @classmethod
    def _screenshots_source_dir(cls, v: object) -> Path | None:
        return _expanded_path(v)

    def effective_screenshots_source_dir(self) -> Path | None:
        """Directory to scan for OS screenshot files; ``None`` disables scanning.

        Defaults are per-platform: macOS drops screenshots on ``~/Desktop`` while
        GNOME/Linux uses ``~/Pictures/Screenshots``. Override via ``SCREENSHOTS_SOURCE_DIR``.
        """
        if not self.screenshots_export_enabled:
            return None
        if self.screenshots_source_dir is not None:
            return self.screenshots_source_dir
        if sys.platform == "darwin":
            return (Path.home() / "Desktop").resolve()
        return (Path.home() / "Pictures" / "Screenshots").resolve()
