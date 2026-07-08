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


def parse_log_level(name: str) -> int:
    """Map ``LOG_LEVEL`` strings to ``logging`` numeric levels (structlog filtering)."""
    key = name.strip().upper()
    if key in ("WARN", "WARNING"):
        key = "WARNING"
    if key in ("FATAL",):
        key = "CRITICAL"
    # logging._nameToLevel includes DEBUG, INFO, WARNING, ERROR, CRITICAL, NOTSET
    return logging._nameToLevel.get(key, logging.INFO)


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

    Set ``LOG_LEVEL=DEBUG`` in the process environment or in ``.env`` (project root).
    ``direnv`` / ``.envrc`` only applies if the shell exports variables **before**
    ``python`` starts; for IDE-launched tasks, prefer ``.env``.
    """
    global _file_handler
    if _file_handler is not None:
        try:
            _file_handler.close()
        except Exception:
            pass
        _file_handler = None

    level = parse_log_level(log_level)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            _file_handler = logging.handlers.RotatingFileHandler(
                str(log_file),
                maxBytes=log_file_max_bytes,
                backupCount=log_file_backup_count,
                encoding="utf-8",
            )
            _file_handler.setFormatter(logging.Formatter("%(message)s"))
        except OSError as e:
            # A misconfigured LOG_FILE (e.g. an unwritable path such as the macOS
            # autofs '/home' mount -> "Operation not supported") must not crash the
            # whole app. Fall back to console-only logging with a warning.
            _file_handler = None
            print(
                f"warning: file logging disabled; cannot use LOG_FILE {log_file}: {e}",
                file=sys.stderr,
            )
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

    # Confirm effective level (helps verify .env / LOG_LEVEL is picked up).
    structlog.get_logger(component="logging").info(
        "logging_configured",
        log_level_setting=log_level.strip() if isinstance(log_level, str) else log_level,
        effective_level=logging.getLevelName(level),
        debug_enabled=level <= logging.DEBUG,
    )


def get_logger(**bound: Any) -> Any:
    return structlog.get_logger().bind(**bound)
