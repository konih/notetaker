from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.observability.logging import configure_logging, get_logger


def test_configure_logging_writes_json_lines_to_file(tmp_path: Path) -> None:
    logf = tmp_path / "out.log"
    configure_logging("INFO", log_file=logf, log_file_max_bytes=1024 * 1024, log_file_backup_count=2)
    get_logger(component="test").info("hello", extra_key=1)
    text = logf.read_text(encoding="utf-8")
    assert "hello" in text
    assert "extra_key" in text
