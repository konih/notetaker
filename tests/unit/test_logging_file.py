from __future__ import annotations

import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from live_meeting_transcriber.observability.logging import configure_logging, get_logger


def test_configure_logging_writes_json_lines_to_file(tmp_path: Path) -> None:
    logf = tmp_path / "out.log"
    configure_logging(
        "INFO", log_file=logf, log_file_max_bytes=1024 * 1024, log_file_backup_count=2
    )
    get_logger(component="test").info("hello", extra_key=1)
    text = logf.read_text(encoding="utf-8")
    assert "hello" in text
    assert "extra_key" in text


def test_configure_logging_survives_uncreatable_log_dir(tmp_path: Path) -> None:
    """A LOG_FILE whose parent can't be created (e.g. macOS autofs '/home' ->

    'Operation not supported') must degrade to console-only logging, not crash.
    """
    logf = tmp_path / "nope" / "out.log"
    err = io.StringIO()
    try:
        with (
            patch(
                "pathlib.Path.mkdir",
                side_effect=OSError(45, "Operation not supported"),
            ),
            contextlib.redirect_stderr(err),
        ):
            configure_logging("INFO", log_file=logf)  # must not raise
        assert "file logging disabled" in err.getvalue()
    finally:
        # Reset global logging state so later tests don't inherit the degraded config.
        configure_logging("INFO")
