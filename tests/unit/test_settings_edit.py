"""U21 — pure logic for the editable settings form (path fields + validation)."""

from __future__ import annotations

from pathlib import Path

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.ui.tui.settings_edit import (
    PATH_SETTING_SPECS,
    apply_path_edits,
    current_path,
    validate_path_selection,
)


def test_specs_cover_all_optional_path_fields() -> None:
    fields = {spec.field for spec in PATH_SETTING_SPECS}
    assert fields == {
        "log_file",
        "obsidian_people_dir",
        "obsidian_meetings_dir",
        "obsidian_meeting_template",
        "obsidian_person_template",
        "obsidian_screenshots_dir",
        "screenshots_source_dir",
    }
    # every path spec maps to a real Path|None field on Settings
    for spec in PATH_SETTING_SPECS:
        assert spec.field in Settings.model_fields
        assert spec.kind in ("dir", "file")


def test_current_path_reads_field(tmp_path: Path) -> None:
    s = Settings.model_construct(obsidian_people_dir=tmp_path, log_file=None)
    assert current_path(s, "obsidian_people_dir") == tmp_path
    assert current_path(s, "log_file") is None


def test_apply_path_edits_sets_and_clears(tmp_path: Path) -> None:
    people = tmp_path / "People"
    people.mkdir()
    base = Settings.model_construct(obsidian_people_dir=None, log_file=tmp_path / "x.log")
    edited = apply_path_edits(
        base, {"obsidian_people_dir": people.resolve(), "log_file": None}
    )
    assert edited.obsidian_people_dir == people.resolve()
    assert edited.log_file is None
    # untouched fields preserved
    assert edited.transcription_model == base.transcription_model


def test_apply_path_edits_empty_is_noop(tmp_path: Path) -> None:
    base = Settings.model_construct(obsidian_people_dir=tmp_path)
    assert apply_path_edits(base, {}).obsidian_people_dir == tmp_path


def test_validate_dir_ok(tmp_path: Path) -> None:
    assert validate_path_selection(tmp_path, "dir") is None


def test_validate_file_ok(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("x", encoding="utf-8")
    assert validate_path_selection(f, "file") is None


def test_validate_nonexistent_blocked(tmp_path: Path) -> None:
    msg = validate_path_selection(tmp_path / "missing", "dir")
    assert msg is not None
    assert "does not exist" in msg.lower()


def test_validate_wrong_kind_blocked(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("x", encoding="utf-8")
    assert validate_path_selection(f, "dir") is not None  # file given, dir expected
    assert validate_path_selection(tmp_path, "file") is not None  # dir given, file expected
