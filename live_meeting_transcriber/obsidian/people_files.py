from __future__ import annotations

import re
from pathlib import Path


def sanitize_note_filename(name: str) -> str:
    """Safe single-segment filename stem (no path separators)."""
    s = name.strip()
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s or "Person"


def list_people_display_names(people_dir: Path) -> list[str]:
    """Basenames of ``*.md`` in the vault people folder (filename without ``.md``)."""
    if not people_dir.is_dir():
        return []
    names: list[str] = []
    for p in sorted(people_dir.glob("*.md"), key=lambda x: x.name.casefold()):
        if p.is_file():
            names.append(p.stem)
    return names


def person_note_path(people_dir: Path, display_name: str) -> Path:
    return (people_dir / f"{sanitize_note_filename(display_name)}.md").resolve()


def person_note_exists(people_dir: Path, display_name: str) -> bool:
    """True if a note exists with the same case-insensitive stem."""
    target = sanitize_note_filename(display_name).casefold()
    for p in people_dir.glob("*.md"):
        if p.is_file() and p.stem.casefold() == target:
            return True
    return False


def render_person_from_template(
    *,
    display_name: str,
    template_text: str,
    note_date: str,
) -> str:
    """Substitute ``{{title}}`` and ``{{date}}`` in the person template."""
    title = display_name.strip()
    body = template_text.replace("{{title}}", title)
    body = body.replace("{{date}}", note_date)
    return body


def write_new_person_note(
    *,
    display_name: str,
    people_dir: Path,
    template_path: Path,
    note_date: str,
) -> Path | None:
    """Create ``People/<Name>.md`` from template if it does not already exist. Returns path if written."""
    people_dir.mkdir(parents=True, exist_ok=True)
    if person_note_exists(people_dir, display_name):
        return None
    stem = sanitize_note_filename(display_name)
    out = people_dir / f"{stem}.md"
    template_text = template_path.read_text(encoding="utf-8")
    out.write_text(
        render_person_from_template(
            display_name=display_name,
            template_text=template_text,
            note_date=note_date,
        ),
        encoding="utf-8",
    )
    return out
