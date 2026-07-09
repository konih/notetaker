"""Pure view-model for the editable Settings screen (U21).

Describes the path-typed settings that are edited through a folder/file picker and the
small amount of logic (apply edits, validate a selection) that can be unit-tested without
a running Textual app. The screen widgets in ``app.py`` are a thin shell over this.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from live_meeting_transcriber.config.settings import Settings

PathKind = Literal["dir", "file"]


@dataclass(frozen=True)
class PathSettingSpec:
    """A ``Path | None`` setting the operator sets via a picker rather than typing."""

    field: str
    label: str
    kind: PathKind
    help: str


# Ordered for display. Every entry is a ``Path | None`` field on :class:`Settings`; all are
# optional (clearable to ``None``) — that is what "not configured" means for these.
PATH_SETTING_SPECS: tuple[PathSettingSpec, ...] = (
    PathSettingSpec(
        "obsidian_people_dir", "Obsidian people folder", "dir", "People notes for autocomplete"
    ),
    PathSettingSpec(
        "obsidian_meetings_dir", "Obsidian meetings folder", "dir", "Where meeting notes export"
    ),
    PathSettingSpec(
        "obsidian_meeting_template", "Meeting note template", "file", "Template for exported notes"
    ),
    PathSettingSpec(
        "obsidian_person_template", "Person note template", "file", "Template for new people"
    ),
    PathSettingSpec(
        "obsidian_screenshots_dir", "Obsidian screenshots folder", "dir", "Where screenshots copy"
    ),
    PathSettingSpec(
        "screenshots_source_dir", "Screenshots source folder", "dir", "Folder scanned for captures"
    ),
    PathSettingSpec("log_file", "Log file", "file", "Application log location"),
)


def current_path(settings: Settings, field: str) -> Path | None:
    """Return the current value of a path field (``None`` when unset)."""
    value = getattr(settings, field)
    return value if value is None else Path(value)


def apply_path_edits(settings: Settings, edits: Mapping[str, Path | None]) -> Settings:
    """Return a copy of ``settings`` with the given path fields replaced.

    ``edits`` maps a field name to its new value (or ``None`` to clear it). Fields absent
    from the mapping are untouched.
    """
    if not edits:
        return settings
    return settings.model_copy(update=dict(edits))


def validate_path_selection(path: Path, kind: PathKind) -> str | None:
    """Return an error message if ``path`` is not a usable selection, else ``None``.

    Blocks nonexistent paths and kind mismatches (a file where a folder is expected and
    vice versa) so the picker can refuse an invalid choice with clear feedback.
    """
    if not path.exists():
        return f"Path does not exist: {path}"
    if kind == "dir" and not path.is_dir():
        return f"Not a folder: {path}"
    if kind == "file" and not path.is_file():
        return f"Not a file: {path}"
    return None
