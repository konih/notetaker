"""Unit tests for import path normalization."""

from __future__ import annotations

from live_meeting_transcriber.application.path_sanitize import normalize_import_path


def test_normalize_import_path_strips_single_quotes() -> None:
    assert normalize_import_path("'tests/fixtures/foo.mp4'") == "tests/fixtures/foo.mp4"


def test_normalize_import_path_strips_double_quotes() -> None:
    assert normalize_import_path('"tests/fixtures/foo.mp4"') == "tests/fixtures/foo.mp4"


def test_normalize_import_path_strips_whitespace() -> None:
    assert normalize_import_path("  /path/to/talk.mp4  ") == "/path/to/talk.mp4"


def test_normalize_import_path_strips_quotes_and_whitespace() -> None:
    assert normalize_import_path("  '/path/to/talk.mp4'  ") == "/path/to/talk.mp4"


def test_normalize_import_path_leaves_urls_unchanged() -> None:
    url = "https://example.com/video.mp4"
    assert normalize_import_path(url) == url


def test_normalize_import_path_leaves_unquoted_paths_unchanged() -> None:
    path = "/home/user/my talk.mp4"
    assert normalize_import_path(path) == path
