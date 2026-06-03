from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path


class ExportWriteDecision(str, Enum):
    write = "write"
    skip_identical = "skip_identical"
    cancelled = "cancelled"


ExportOverwriteConfirm = Callable[[Path], bool]


def normalize_export_content(text: str) -> str:
    """Normalize line endings and trailing whitespace for stable comparison."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    return normalized.rstrip() + "\n"


def export_content_digest(text: str) -> str:
    return hashlib.sha256(normalize_export_content(text).encode("utf-8")).hexdigest()


def export_content_identical(existing: str, new: str) -> bool:
    return export_content_digest(existing) == export_content_digest(new)


def resolve_export_write(
    path: Path,
    new_content: str,
    *,
    confirm_overwrite: ExportOverwriteConfirm | None = None,
) -> ExportWriteDecision:
    """Decide whether to write ``new_content`` to ``path``."""
    normalized = normalize_export_content(new_content)
    if not path.is_file():
        return ExportWriteDecision.write
    existing = path.read_text(encoding="utf-8")
    if export_content_identical(existing, normalized):
        return ExportWriteDecision.skip_identical
    if confirm_overwrite is not None and not confirm_overwrite(path):
        return ExportWriteDecision.cancelled
    return ExportWriteDecision.write


def write_text_from_decision(path: Path, content: str, decision: ExportWriteDecision) -> None:
    if decision in (ExportWriteDecision.skip_identical, ExportWriteDecision.cancelled):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_export_content(content), encoding="utf-8")
