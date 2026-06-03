from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain.models import (
    MeetingMetadataProposal,
    MeetingSession,
    Summary,
)
from live_meeting_transcriber.obsidian.meeting_export import render_meeting_note
from live_meeting_transcriber.summarization.structured_output import parse_structured_summary_output


def test_parse_structured_summary_output_with_metadata() -> None:
    parsed = parse_structured_summary_output(
        {
            "summary_markdown": "## Summary\n- Discussed roadmap",
            "decisions": ["Ship v1"],
            "action_items": ["Write docs"],
            "metadata": {
                "title": "Weekly HI-Kafka Sync",
                "topic": "Kafka mirroring",
                "tags": ["meeting", "kafka", "sync"],
                "participants": ["Alice", "Bob"],
                "series": "Weekly HI-Kafka Sync",
                "location": "Microsoft Teams",
                "confidence": {
                    "title": True,
                    "topic": True,
                    "tags": True,
                    "participants": True,
                    "series": True,
                    "location": True,
                },
            },
        }
    )
    assert parsed.summary_markdown.startswith("## Summary")
    assert parsed.metadata is not None
    assert parsed.metadata.confident_str("title") == "Weekly HI-Kafka Sync"
    assert parsed.metadata.confident_tags() == ["meeting", "kafka", "sync"]


def test_parse_structured_summary_rejects_missing_summary() -> None:
    with pytest.raises(ValueError, match="Invalid structured summary"):
        parse_structured_summary_output({"decisions": []})


def test_render_meeting_note_applies_confident_metadata(tmp_path) -> None:
    tpl = tmp_path / "Meeting.md"
    tpl.write_text(
        "---\n"
        'type: meeting\ndate: "{{date}}"\ntime: "{{time}}"\n'
        'attendees: []\nlocation: ""\ntopic: ""\n'
        'tags: [meeting]\nseries: ""\nrelated: ""\n---\n\n'
        "# {{title}}\n\n## Notes\n- \n\n## Decisions\n- \n\n"
        "## Action items\n- [ ] \n\n## Meeting Transcript\n",
        encoding="utf-8",
    )
    sid = uuid4()
    t0 = datetime(2026, 5, 20, 8, 6, 0)
    session = MeetingSession(id=sid, title="Weekly HI-Kafka Sync", started_at=t0)
    meta = MeetingMetadataProposal(
        title="Weekly HI-Kafka Sync",
        topic="Kafka topic mirroring",
        tags=["meeting", "kafka", "sync"],
        series="Weekly HI-Kafka Sync",
        location="Microsoft Teams",
        confidence={
            "topic": True,
            "tags": True,
            "series": True,
            "location": True,
        },
    )
    summary = Summary(
        session_id=sid,
        summary_markdown="## Summary\n- Mirroring demo",
        meeting_metadata=meta,
    )
    text = render_meeting_note(
        template_text=tpl.read_text(encoding="utf-8"),
        session=session,
        segments=[],
        summary=summary,
    )
    assert 'topic: "Kafka topic mirroring"' in text
    assert 'tags: ["meeting", "kafka", "sync"]' in text
    assert 'series: "Weekly HI-Kafka Sync"' in text
    assert 'location: "Microsoft Teams"' in text
    assert "Mirroring demo" in text
