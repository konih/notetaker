from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.application.export_overwrite import (
    ExportWriteDecision,
    export_content_identical,
    normalize_export_content,
    resolve_export_write,
)


def test_normalize_export_content_strips_trailing_whitespace() -> None:
    assert normalize_export_content("a\nb  \n") == "a\nb\n"


def test_export_content_identical_ignores_trailing_whitespace() -> None:
    assert export_content_identical("hello\n", "hello\n\n  ")


def test_export_content_identical_detects_differences() -> None:
    assert not export_content_identical("hello\n", "hello world\n")


def test_resolve_export_write_new_file(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    assert resolve_export_write(path, "content\n") == ExportWriteDecision.write


def test_resolve_export_write_skips_identical(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    path.write_text("same\n", encoding="utf-8")
    assert resolve_export_write(path, "same\n\n") == ExportWriteDecision.skip_identical


def test_resolve_export_write_prompts_when_different(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    path.write_text("old\n", encoding="utf-8")
    prompted: list[Path] = []

    def confirm(p: Path) -> bool:
        prompted.append(p)
        return False

    assert (
        resolve_export_write(path, "new\n", confirm_overwrite=confirm)
        == ExportWriteDecision.cancelled
    )
    assert prompted == [path]
    assert path.read_text(encoding="utf-8") == "old\n"


def test_resolve_export_write_overwrites_when_confirmed(tmp_path: Path) -> None:
    path = tmp_path / "out.md"
    path.write_text("old\n", encoding="utf-8")
    decision = resolve_export_write(path, "new\n", confirm_overwrite=lambda _: True)
    assert decision == ExportWriteDecision.write
