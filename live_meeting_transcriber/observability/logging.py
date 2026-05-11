from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Any

import structlog

_file_handler_lock = threading.Lock()
_file_handler: logging.handlers.RotatingFileHandler | None = None


def _dup_json_line_to_file(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Processor: append one JSON line per log event to the rotating file (no transcript redaction here)."""
    global _file_handler
    if _file_handler is None:
        return event_dict
    try:
        line = json.dumps(event_dict, default=str, ensure_ascii=False)
        with _file_handler_lock:
            _file_handler.emit(logging.LogRecord("lmt", logging.INFO, "", 0, line, (), None))
    except Exception:
        pass
    return event_dict


def configure_logging(
    log_level: str = "INFO",
    *,
    log_file: Path | None = None,
    log_file_max_bytes: int = 10 * 1024 * 1024,
    log_file_backup_count: int = 5,
) -> None:
    """Configure structlog JSON to stdout and optional rotating JSON-lines file.

    File sink receives the same structured event dict as stdout (still no automatic
    redaction of transcript fields — avoid logging raw transcript text at INFO).
    """
    global _file_handler
    if _file_handler is not None:
        try:
            _file_handler.close()
        except Exception:
            pass
        _file_handler = None

    level = getattr(logging, log_level.upper(), logging.INFO)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.handlers.RotatingFileHandler(
            str(log_file),
            maxBytes=log_file_max_bytes,
            backupCount=log_file_backup_count,
            encoding="utf-8",
        )
        _file_handler.setFormatter(logging.Formatter("%(message)s"))
    else:
        _file_handler = None

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if _file_handler is not None:
        processors.append(_dup_json_line_to_file)
    processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(**bound: Any) -> Any:
    return structlog.get_logger().bind(**bound)
