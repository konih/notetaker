from __future__ import annotations

import re
from pathlib import Path

from live_meeting_transcriber.domain.models import MeetingSession, Summary, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


def _slug_title(title: str, max_len: int = 48) -> str:
    s = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return (s[:max_len] if s else "session").rstrip("-")


def export_filename_for_session(session: MeetingSession) -> str:
    return f"{session.id}_{_slug_title(session.title)}.md"


def build_session_export_markdown(
    *,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
) -> str:
    disp = speaker_display or {}
    lines: list[str] = []
    lines.append(f"## {session.title}")
    lines.append("")
    lines.append(f"- **Session ID**: `{session.id}`")
    lines.append(f"- **Started**: {session.started_at.isoformat()}")
    lines.append(f"- **Ended**: {session.ended_at.isoformat() if session.ended_at else ''}")
    if session.attendees:
        lines.append(f"- **Attendees**: {', '.join(session.attendees)}")
    lines.append("")
    if session.notes.strip():
        lines.append("### Meeting notes")
        lines.append("")
        lines.append(session.notes.strip())
        lines.append("")

    if summary:
        lines.append("### Summary")
        lines.append("")
        lines.append(summary.summary_markdown)
        lines.append("")
        if summary.decisions:
            lines.append("### Decisions")
            lines.append("")
            for d in summary.decisions:
                lines.append(f"- {d.text}")
            lines.append("")
        if summary.action_items:
            lines.append("### Action items")
            lines.append("")
            for ai in summary.action_items:
                lines.append(f"- {ai.text}")
            lines.append("")

    lines.append("### Transcript")
    lines.append("")
    if transcript_lines is not None:
        lines.extend(transcript_lines)
    else:
        for s in segments:
            label = format_transcript_speaker_label(s.speaker, disp)
            lines.append(f"- [{s.started_at.isoformat()}] {label}: {s.text}")

    return "\n".join(lines)


def write_session_export_markdown(
    *,
    base_dir: Path,
    session: MeetingSession,
    segments: list[TranscriptSegment],
    summary: Summary | None,
    speaker_display: dict[str, str] | None = None,
    transcript_lines: list[str] | None = None,
) -> Path:
    out_dir = (base_dir / "exports").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / export_filename_for_session(session)
    path.write_text(
        build_session_export_markdown(
            session=session,
            segments=segments,
            summary=summary,
            speaker_display=speaker_display,
            transcript_lines=transcript_lines,
        ),
        encoding="utf-8",
    )
    return path
