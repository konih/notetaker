from __future__ import annotations

from collections.abc import Iterable

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


def build_summary_prompt(
    *,
    session: MeetingSession,
    segments: Iterable[TranscriptSegment],
    speaker_display: dict[str, str] | None = None,
) -> str:
    # Intentionally simple; prompt engineering can evolve without affecting domain.
    disp = speaker_display or {}
    lines: list[str] = []
    lines.append("You are a careful meeting assistant.")
    lines.append("")
    lines.append(f"Meeting title: {session.title}")
    if session.attendees:
        lines.append(f"People attending (from notes): {', '.join(session.attendees)}")
    if session.notes.strip():
        lines.append("")
        lines.append("Meeting notes (context):")
        lines.append(session.notes.strip())
    lines.append("")
    lines.append("Transcript (chronological):")
    for s in segments:
        # Avoid leaking provider metadata; only use text and coarse timestamps.
        label = format_transcript_speaker_label(s.speaker, disp)
        lines.append(f"- [{s.started_at.isoformat()} → {s.ended_at.isoformat()}] {label}: {s.text}")
    lines.append("")
    lines.append("Return a JSON object with keys:")
    lines.append("- summary_markdown (string, markdown)")
    lines.append("- decisions (array of strings)")
    lines.append("- action_items (array of strings)")
    return "\n".join(lines)
