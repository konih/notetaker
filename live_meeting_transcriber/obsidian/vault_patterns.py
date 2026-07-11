from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from live_meeting_transcriber.domain.meeting_naming import is_placeholder_meeting_title

__all__ = [
    "VaultNamingHints",
    "is_placeholder_meeting_title",
    "load_vault_naming_hints",
    "safe_obsidian_filename_title",
]


@dataclass(frozen=True)
class VaultNamingHints:
    """Patterns inferred from existing Obsidian meeting notes."""

    sample_titles: tuple[str, ...] = ()
    common_tags: tuple[str, ...] = ()
    uses_descriptive_filenames: bool = True


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_TAGS_RE = re.compile(r"^tags:\s*\[(.*)\]\s*$", re.MULTILINE)


def _parse_tags(block: str) -> list[str]:
    m = _TAGS_RE.search(block)
    if not m:
        return []
    inner = m.group(1).strip()
    if not inner:
        return []
    return [t.strip().strip('"').strip("'") for t in inner.split(",") if t.strip()]


def _title_from_note(path: Path, text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    stem = path.stem
    if re.match(r"^\d{4}-\d{2}-\d{2}\s+", stem):
        return stem[11:].strip()
    return None


def load_vault_naming_hints(meetings_dir: Path | None, *, max_files: int = 40) -> VaultNamingHints:
    """Scan ``meetings_dir`` for title and tag patterns (best-effort)."""
    if meetings_dir is None or not meetings_dir.is_dir():
        return VaultNamingHints()

    titles: list[str] = []
    tag_counts: Counter[str] = Counter()
    descriptive_names = 0
    slug_names = 0

    files = sorted(meetings_dir.glob("*.md"))[:max_files]
    for path in files:
        if path.name.lower() in ("regular meetings.md",):
            continue
        stem = path.stem
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+.+", stem):
            descriptive_names += 1
        elif re.match(r"^\d{4}-\d{2}-\d{2}_", stem):
            slug_names += 1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = _title_from_note(path, text)
        if title and not is_placeholder_meeting_title(title):
            titles.append(title)
        fm = _FRONTMATTER_RE.match(text)
        if fm:
            for tag in _parse_tags(fm.group(1)):
                if tag:
                    tag_counts[tag.lower()] += 1

    common_tags = tuple(t for t, _ in tag_counts.most_common(12) if t != "meeting")
    sample_titles = tuple(list(dict.fromkeys(titles))[:10])
    uses_descriptive = descriptive_names >= slug_names
    return VaultNamingHints(
        sample_titles=sample_titles,
        common_tags=common_tags,
        uses_descriptive_filenames=uses_descriptive,
    )


def safe_obsidian_filename_title(title: str, *, max_len: int = 96) -> str:
    """Filesystem-safe title segment matching vault ``YYYY-MM-DD Title.md`` style."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "meeting"
    return cleaned[:max_len].rstrip(" .")
