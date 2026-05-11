from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.domain.models import (
    MeetingSession,
    SpeakerLabel,
    Summary,
    TranscriptSegment,
)
from live_meeting_transcriber.obsidian.meeting_export import render_meeting_note
from live_meeting_transcriber.obsidian.people_files import (
    list_people_display_names,
    person_note_exists,
    write_new_person_note,
)
from live_meeting_transcriber.storage.people_composite import CompositeKnownPeopleRepository
from live_meeting_transcriber.storage.repositories import SqliteKnownPeopleRepository
from live_meeting_transcriber.storage.sqlite import open_connection


def test_list_people_from_vault(tmp_path) -> None:
    p = tmp_path / "People"
    p.mkdir()
    (p / "Alice One.md").write_text("x", encoding="utf-8")
    (p / "Bob Two.md").write_text("y", encoding="utf-8")
    names = list_people_display_names(p)
    assert names == ["Alice One", "Bob Two"]


def test_create_person_note_uses_template(tmp_path) -> None:
    people = tmp_path / "People"
    tpl = tmp_path / "Person.md"
    tpl.write_text("# {{title}}\n\ndate: {{date}}\n", encoding="utf-8")
    out = write_new_person_note(
        display_name="New Person",
        people_dir=people,
        template_path=tpl,
        note_date="2026-05-11",
    )
    assert out is not None
    text = out.read_text(encoding="utf-8")
    assert "# New Person" in text
    assert "2026-05-11" in text
    assert (
        write_new_person_note(
            display_name="New Person",
            people_dir=people,
            template_path=tpl,
            note_date="2026-05-11",
        )
        is None
    )


def test_render_meeting_note(tmp_path) -> None:
    tpl = tmp_path / "Meeting.md"
    tpl.write_text(
        '---\ntype: meeting\ndate: "{{date}}"\nattendees: []\n---\n\n# {{title}}\n\n'
        "## Notes\n- \n\n## Decisions\n- \n\n## Action items\n- [ ] \n\n## Meeting Transcript\n",
        encoding="utf-8",
    )
    sid = uuid4()
    t0 = datetime(2026, 5, 11, 14, 30, 0)
    session = MeetingSession(
        id=sid,
        title="Sync",
        started_at=t0,
        ended_at=t0 + timedelta(hours=1),
        notes="Quick notes",
        attendees=["Alice"],
    )
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        text="Hello",
        speaker=SpeakerLabel.speaker_1,
    )
    summary = Summary(
        session_id=sid, summary_markdown="## Sum\nDone", decisions=[], action_items=[]
    )
    text = render_meeting_note(
        template_text=tpl.read_text(encoding="utf-8"),
        session=session,
        segments=[seg],
        summary=summary,
        speaker_display={"speaker_1": "Alice"},
    )
    assert "2026-05-11" in text
    assert "14:30" in text
    assert "# Sync" in text
    assert "Alice" in text
    assert "Quick notes" in text
    assert "Done" in text
    assert "**Alice**" in text or "Alice**" in text


def test_composite_merges_vault_and_sqlite(tmp_path) -> None:
    vault = tmp_path / "People"
    vault.mkdir()
    (vault / "Vault Only.md").write_text("-", encoding="utf-8")
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        inner = SqliteKnownPeopleRepository(conn)
        inner.touch("Db Only")
        comp = CompositeKnownPeopleRepository(
            inner=inner,
            people_dir=vault,
            person_template=None,
        )
        names = comp.search_prefix("vault", limit=20)
        assert "Vault Only" in names
        names_db = comp.search_prefix("db", limit=20)
        assert "Db Only" in names_db
    finally:
        conn.close()


def test_touch_creates_person_file_when_configured(tmp_path) -> None:
    vault = tmp_path / "People"
    vault.mkdir()
    tpl = tmp_path / "Person.md"
    tpl.write_text("# {{title}}\n{{date}}\n", encoding="utf-8")
    conn = open_connection(f"sqlite:////{tmp_path}/db.sqlite3")
    try:
        inner = SqliteKnownPeopleRepository(conn)
        comp = CompositeKnownPeopleRepository(inner=inner, people_dir=vault, person_template=tpl)
        comp.touch("Fresh Name")
        assert person_note_exists(vault, "Fresh Name")
    finally:
        conn.close()
