"""U21/U15 — pure logic for the editable settings form (path + scalar fields, validation)."""

from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.config.settings import SECRET_FIELD_NAMES, Settings
from live_meeting_transcriber.ui.tui.settings_edit import (
    PATH_SETTING_SPECS,
    SCALAR_SETTING_SPECS,
    apply_path_edits,
    apply_scalar_edits,
    current_path,
    current_scalar,
    parse_scalar_text,
    validate_path_selection,
    validate_scalar_edits,
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
    edited = apply_path_edits(base, {"obsidian_people_dir": people.resolve(), "log_file": None})
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


# --- U15: safe runtime scalar toggles -----------------------------------------------------


def test_scalar_specs_cover_approved_safe_toggles() -> None:
    """The operator-approved safe subset (UX-OQ-2): a handful, no secrets, no paths."""
    fields = {spec.field for spec in SCALAR_SETTING_SPECS}
    assert fields == {
        "finalize_on_session_stop",
        "audio_silence_skip_enabled",
        "audio_silence_threshold_dbfs",
        "keep_audio_chunks",
        "audio_chunk_seconds",
    }
    path_fields = {spec.field for spec in PATH_SETTING_SPECS}
    for spec in SCALAR_SETTING_SPECS:
        assert spec.field in Settings.model_fields
        assert spec.field not in SECRET_FIELD_NAMES
        assert spec.field not in path_fields
        assert spec.kind in ("bool", "int", "float")
        assert spec.label
        assert spec.help


def test_scalar_spec_kinds_match_model() -> None:
    kinds = {spec.field: spec.kind for spec in SCALAR_SETTING_SPECS}
    assert kinds["finalize_on_session_stop"] == "bool"
    assert kinds["audio_silence_skip_enabled"] == "bool"
    assert kinds["keep_audio_chunks"] == "bool"
    assert kinds["audio_silence_threshold_dbfs"] == "float"
    assert kinds["audio_chunk_seconds"] == "int"


def test_current_scalar_reads_field() -> None:
    s = Settings.model_construct(audio_chunk_seconds=25, keep_audio_chunks=True)
    assert current_scalar(s, "audio_chunk_seconds") == 25
    assert current_scalar(s, "keep_audio_chunks") is True


def test_parse_scalar_text_int_and_float() -> None:
    assert parse_scalar_text("int", " 30 ") == 30
    assert parse_scalar_text("float", "-55.5") == -55.5
    assert parse_scalar_text("float", "-70") == -70.0


def test_parse_scalar_text_rejects_garbage() -> None:
    assert parse_scalar_text("int", "abc") is None
    assert parse_scalar_text("int", "1.5") is None
    assert parse_scalar_text("int", "") is None
    assert parse_scalar_text("float", "ten") is None
    assert parse_scalar_text("float", "   ") is None


def test_validate_scalar_edits_ok() -> None:
    s = Settings()
    ok = validate_scalar_edits(
        s,
        {
            "audio_chunk_seconds": 30,
            "audio_silence_threshold_dbfs": -55.0,
            "keep_audio_chunks": True,
        },
    )
    assert ok == {}


def test_validate_scalar_edits_flags_out_of_range_per_field() -> None:
    s = Settings()
    errs = validate_scalar_edits(s, {"audio_silence_threshold_dbfs": -200.0})
    assert set(errs) == {"audio_silence_threshold_dbfs"}
    assert errs["audio_silence_threshold_dbfs"]  # human-readable message

    errs2 = validate_scalar_edits(s, {"audio_chunk_seconds": 0})
    assert set(errs2) == {"audio_chunk_seconds"}

    errs3 = validate_scalar_edits(s, {"audio_chunk_seconds": 301})
    assert set(errs3) == {"audio_chunk_seconds"}


def test_validate_scalar_edits_empty_is_ok() -> None:
    assert validate_scalar_edits(Settings(), {}) == {}


def test_apply_scalar_edits_sets_and_preserves() -> None:
    s = Settings()
    edited = apply_scalar_edits(s, {"keep_audio_chunks": True, "audio_chunk_seconds": 20})
    assert edited.keep_audio_chunks is True
    assert edited.audio_chunk_seconds == 20
    # untouched fields preserved
    assert edited.transcription_model == s.transcription_model
    assert edited.audio_silence_threshold_dbfs == s.audio_silence_threshold_dbfs


def test_apply_scalar_edits_empty_is_noop() -> None:
    s = Settings.model_construct(audio_chunk_seconds=25)
    assert apply_scalar_edits(s, {}).audio_chunk_seconds == 25
