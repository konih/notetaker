"""Render Obsidian-vault meeting notes (template fill, naming, frontmatter).

Rendering only (A9): writing files and orchestrating the dual export live in
:mod:`live_meeting_transcriber.application.dual_export`, which talks to this adapter
through the ``MeetingNoteRenderer`` port (implemented here by
:class:`ObsidianMeetingNoteRenderer`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from live_meeting_transcriber.domain.exceptions import ExportCancelledError
from live_meeting_transcriber.domain.meeting_naming import slug_title
from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.obsidian.vault_patterns import (
    is_placeholder_meeting_title,
    safe_obsidian_filename_title,
)

__all__ = [
    "ExportCancelledError",
    "ObsidianMeetingNoteRenderer",
    "meeting_export_filename",
    "render_meeting_note",
]


def _yaml_attendees_list(names: list[str]) -> str:
    if not names:
        return "[]"
    escaped = [n.replace('"', '\\"') for n in names]
    inner = ", ".join(f'"{x}"' for x in escaped)
    return f"[{inner}]"


def _yaml_tags_list(tags: list[str]) -> str:
    if not tags:
        return "[meeting]"
    escaped = [t.replace('"', '\\"') for t in tags]
    inner = ", ".join(f'"{x}"' for x in escaped)
    return f"[{inner}]"


def _replace_frontmatter_scalar(content: str, key: str, value: str) -> str:
    quoted = value.replace('"', '\\"')
    replacement = f'{key}: "{quoted}"' if value else f'{key}: ""'
    pattern = rf"^{re.escape(key)}:\s*.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
    return content


def _replace_frontmatter_list(content: str, key: str, values: list[str]) -> str:
    if key == "attendees":
        rendered = _yaml_attendees_list(values)
    elif key == "tags":
        rendered = _yaml_tags_list(values)
    else:
        rendered = _yaml_attendees_list(values)
    pattern = rf"^{re.escape(key)}:\s*.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, f"{key}: {rendered}", content, count=1, flags=re.MULTILINE)
    return content


def _replace_under_heading(content: str, heading: str, new_body: str) -> str:
    """Replace everything under ``## {heading}`` until the next ``##`` at line start."""
    marker = f"## {heading}\n"
    idx = content.find(marker)
    if idx == -1:
        return content
    start = idx + len(marker)
    rest = content[start:]
    next_h = re.search(r"\n## ", rest)
    end_rel = next_h.start() if next_h else len(rest)
    return content[:start] + new_body.strip() + "\n" + rest[end_rel:]


def _effective_attendees(session: MeetingSession, summary: Summary | None) -> list[str]:
    attendees = list(session.attendees)
    meta = summary.meeting_metadata if summary else None
    if meta is not None:
        for name in meta.confident_participants():
            if name not in attendees:
                attendees.append(name)
    return attendees


def _apply_summary_metadata_to_template(body: str, summary: Summary | None) -> str:
    meta = summary.meeting_metadata if summary else None
    if meta is None:
        return body

    topic = meta.confident_str("topic")
    if topic:
        body = _replace_frontmatter_scalar(body, "topic", topic)

    tags = meta.confident_tags()
    if tags:
        body = _replace_frontmatter_list(body, "tags", tags)

    series = meta.confident_str("series")
    if series:
        body = _replace_frontmatter_scalar(body, "series", series)

    location = meta.confident_str("location")
    if location:
        body = _replace_frontmatter_scalar(body, "location", location)

    related = meta.confident_str("related")
    if related:
        body = _replace_frontmatter_scalar(body, "related", related)

    return body


def render_meeting_note(
    *,
    template_text: str,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
) -> str:
    """Fill ``Templates/Meeting.md``-style placeholders and inject notes / summary / transcript."""
    disp = speaker_display or {}
    d = session.started_at.date().isoformat()
    t = session.started_at.strftime("%H:%M")
    attendees = _effective_attendees(session, summary)
    body = template_text.replace("{{date}}", d)
    body = body.replace("{{time}}", t)
    body = body.replace("{{title}}", session.title)
    body = re.sub(
        r"^attendees:\s*\[\s*\]\s*$",
        f"attendees: {_yaml_attendees_list(attendees)}",
        body,
        flags=re.MULTILINE,
    )
    if attendees:
        body = re.sub(
            r"^(- \*\*Attendees\*\*:)\s*$",
            rf"\1 {', '.join(attendees)}",
            body,
            flags=re.MULTILINE,
        )

    body = _apply_summary_metadata_to_template(body, summary)

    notes_parts: list[str] = []
    if session.notes.strip():
        notes_parts.append(session.notes.strip())
    if summary and summary.summary_markdown.strip():
        notes_parts.append(summary.summary_markdown.strip())
    notes_block = "\n\n".join(notes_parts) if notes_parts else "_—_"

    decisions_block = (
        "\n".join(f"- {x.text}" for x in summary.decisions)
        if summary and summary.decisions
        else "- _—_"
    )
    actions_block = (
        "\n".join(f"- [ ] {x.text}" for x in summary.action_items)
        if summary and summary.action_items
        else "- [ ] _—_"
    )

    if transcript_lines is not None:
        transcript_block = "\n".join(transcript_lines) if transcript_lines else "- _—_"
    else:
        tlines: list[str] = []
        for seg in segments:
            label = format_transcript_speaker_label(seg.speaker, disp)
            tlines.append(f"- [{seg.started_at.isoformat()}] **{label}**: {seg.text}")
        transcript_block = "\n".join(tlines) if tlines else "- _—_"

    body = _replace_under_heading(body, "Notes", notes_block)
    body = _replace_under_heading(body, "Decisions", decisions_block)
    body = _replace_under_heading(body, "Action items", actions_block)
    body = _replace_under_heading(body, "Meeting Transcript", transcript_block)

    return body.rstrip() + "\n"


def meeting_export_filename(session: MeetingSession) -> str:
    """Stable filename: ``YYYY-MM-DD Title.md`` when title is meaningful, else slug form."""
    day = session.started_at.date().isoformat()
    if not is_placeholder_meeting_title(session.title):
        safe = safe_obsidian_filename_title(session.title)
        return f"{day} {safe}.md"
    slug = slug_title(session.title, max_len=56)
    return f"{day}_{slug}.md"


@dataclass(frozen=True)
class ObsidianMeetingNoteRenderer:
    """``MeetingNoteRenderer`` port implementation for the Obsidian vault.

    ``note_path`` returns ``None`` (vault export disabled) unless both the meetings
    dir and an existing template file are configured.
    """

    meetings_dir: Path | None
    template_path: Path | None

    def note_path(self, session: MeetingSession) -> Path | None:
        if self.meetings_dir is None or self.template_path is None:
            return None
        if not self.template_path.is_file():
            return None
        return self.meetings_dir / meeting_export_filename(session)

    def screenshots_dir(self, note_path: Path) -> Path:
        return (note_path.parent.parent / "Images" / "Screenshots").resolve()

    def render(
        self,
        *,
        session: MeetingSession,
        segments: list[TranscriptSegment],
        summary: Summary | None,
        speaker_display: dict[str, str] | None = None,
        transcript_lines: list[str] | None = None,
    ) -> str:
        if self.template_path is None:
            raise ValueError("Obsidian meeting template is not configured")
        template_text = self.template_path.read_text(encoding="utf-8")
        return render_meeting_note(
            template_text=template_text,
            session=session,
            segments=segments,
            summary=summary,
            speaker_display=speaker_display,
            transcript_lines=transcript_lines,
        )
