from __future__ import annotations

from pathlib import Path

from live_meeting_transcriber.obsidian.vault_patterns import (
    is_placeholder_meeting_title,
    load_vault_naming_hints,
)


def test_load_vault_naming_hints_from_fixture_vault() -> None:
    meetings_dir = Path.home() / "Projects" / "Obsidian" / "Notes" / "Meetings"
    if not meetings_dir.is_dir():
        return
    hints = load_vault_naming_hints(meetings_dir)
    assert hints.sample_titles
    assert hints.uses_descriptive_filenames


def test_is_placeholder_meeting_title() -> None:
    assert is_placeholder_meeting_title("Meeting")
    assert is_placeholder_meeting_title("Meeting 2026-06-03T11:03:27")
    assert not is_placeholder_meeting_title("Weekly HI-Kafka Sync")
