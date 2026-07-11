"""Pure view-model for the editable Settings screen (U21, U15).

Describes the path-typed settings that are edited through a folder/file picker (U21), the
operator-approved safe runtime scalar toggles that are edited inline (U15, UX-OQ-2), and
the small amount of logic (apply edits, parse/validate input) that can be unit-tested
without a running Textual app. The screen widgets in ``app.py`` are a thin shell over this.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from live_meeting_transcriber.config.settings import Settings

PathKind = Literal["dir", "file"]
ScalarKind = Literal["bool", "int", "float"]
ScalarValue = bool | int | float


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


@dataclass(frozen=True)
class ScalarSettingSpec:
    """A safe runtime scalar setting edited inline (U15, operator decision UX-OQ-2).

    Deliberately a small allowlist — not a full settings editor. Every entry is a
    non-secret bool/int/float field on :class:`Settings`; ``bool`` renders as a switch,
    ``int``/``float`` as a validated text input. All of them are read from the Settings
    instance captured at app/recorder construction, so edits apply after restart
    (matching the U21 precedent; no live re-threading of running components).
    """

    field: str
    label: str
    kind: ScalarKind
    help: str


# Ordered for display. Chosen set per UX-OQ-2 ("a handful of safe runtime toggles only").
SCALAR_SETTING_SPECS: tuple[ScalarSettingSpec, ...] = (
    ScalarSettingSpec(
        "finalize_on_session_stop",
        "Label speakers after meeting",
        "bool",
        "Queue the offline Speaker ID pass when a recording stops",
    ),
    ScalarSettingSpec(
        "audio_silence_skip_enabled",
        "Skip silent chunks",
        "bool",
        "Don't transcribe near-silent audio chunks (audio is still recorded)",
    ),
    ScalarSettingSpec(
        "audio_silence_threshold_dbfs",
        "Silence threshold (dBFS)",
        "float",
        "RMS level below which a chunk counts as silent (-120 to 0)",
    ),
    ScalarSettingSpec(
        "keep_audio_chunks",
        "Keep audio chunks",
        "bool",
        "Keep per-chunk WAV files after transcription instead of deleting them",
    ),
    ScalarSettingSpec(
        "audio_chunk_seconds",
        "Chunk length (seconds)",
        "int",
        "Length of each live transcription chunk (1 to 300)",
    ),
)


def current_scalar(settings: Settings, field: str) -> ScalarValue:
    """Return the current value of a scalar field."""
    value: ScalarValue = getattr(settings, field)
    return value


def parse_scalar_text(kind: Literal["int", "float"], raw: str) -> int | float | None:
    """Parse the text of a numeric input; ``None`` when it is not a valid number."""
    text = raw.strip()
    if not text:
        return None
    try:
        return int(text) if kind == "int" else float(text)
    except ValueError:
        return None


def validate_scalar_edits(settings: Settings, edits: Mapping[str, ScalarValue]) -> dict[str, str]:
    """Validate scalar edits against the Settings model's own constraints.

    Returns ``{field: error message}`` for every edited field pydantic rejects (e.g. a
    threshold outside -120..0); an empty dict means the edits are valid. Reuses the model
    constraints so the form can never drift from what ``Settings`` itself accepts.
    ``model_validate`` checks the merged data directly — it does not re-read env/YAML
    sources, so validation is deterministic in tests and in the running app.
    """
    if not edits:
        return {}
    merged = settings.model_dump() | dict(edits)
    try:
        Settings.model_validate(merged)
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for err in exc.errors():
            loc = str(err["loc"][0]) if err["loc"] else ""
            field = loc if loc in edits else next(iter(edits))
            errors.setdefault(field, err["msg"])
        return errors
    return {}


def apply_scalar_edits(settings: Settings, edits: Mapping[str, ScalarValue]) -> Settings:
    """Return a copy of ``settings`` with the given scalar fields replaced.

    Mirrors :func:`apply_path_edits`; callers must validate via
    :func:`validate_scalar_edits` first (``model_copy`` does not re-run constraints).
    """
    if not edits:
        return settings
    return settings.model_copy(update=dict(edits))
