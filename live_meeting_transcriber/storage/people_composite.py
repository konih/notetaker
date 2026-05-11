from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from live_meeting_transcriber.obsidian.people_files import (
    list_people_display_names,
    person_note_exists,
    write_new_person_note,
)
from live_meeting_transcriber.storage.repositories import SqliteKnownPeopleRepository


def _merge_name_lists(*lists: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for n in lst:
            k = n.casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(n)
            if len(out) >= limit:
                return out
    return out


def _filter_prefix(names: list[str], prefix: str) -> list[str]:
    p = prefix.casefold()
    return [n for n in names if n.casefold().startswith(p)]


@dataclass(frozen=True)
class CompositeKnownPeopleRepository:
    """SQLite touch + search merged with Obsidian ``People/*.md`` names; creates person notes from template."""

    inner: SqliteKnownPeopleRepository
    people_dir: Path | None
    person_template: Path | None

    @property
    def conn(self) -> Any:
        return self.inner.conn

    def _vault_names(self) -> list[str]:
        if self.people_dir is None or not self.people_dir.is_dir():
            return []
        return list_people_display_names(self.people_dir)

    def list_for_autocomplete(self) -> list[str]:
        vault = self._vault_names()
        db = self.inner.list_for_autocomplete()
        return _merge_name_lists(vault, db, limit=500)

    def search_prefix(self, prefix: str, *, limit: int = 25) -> list[str]:
        p = prefix.strip()
        vault = self._vault_names()
        if not p:
            return _merge_name_lists(vault, self.inner.list_for_autocomplete(), limit=limit)
        v_hit = _filter_prefix(vault, p)
        db_hit = self.inner.search_prefix(p, limit=limit)
        return _merge_name_lists(v_hit, db_hit, limit=limit)

    def touch(self, display_name: str) -> None:
        self.inner.touch(display_name)
        if (
            self.people_dir is not None
            and self.person_template is not None
            and self.person_template.is_file()
            and not person_note_exists(self.people_dir, display_name)
        ):
            note_date = datetime.utcnow().date().isoformat()
            write_new_person_note(
                display_name=display_name,
                people_dir=self.people_dir,
                template_path=self.person_template,
                note_date=note_date,
            )
