from __future__ import annotations

from collections.abc import Iterable

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment


def build_summary_prompt(*, session: MeetingSession, segments: Iterable[TranscriptSegment]) -> str:
    # Intentionally simple; prompt engineering can evolve without affecting domain.
    lines: list[str] = []
    lines.append("You are a careful meeting assistant.")
    lines.append("")
    lines.append(f"Meeting title: {session.title}")
    lines.append("")
    lines.append("Transcript (chronological):")
    for s in segments:
        # Avoid leaking provider metadata; only use text and coarse timestamps.
        lines.append(f"- [{s.started_at.isoformat()} → {s.ended_at.isoformat()}] {s.speaker.value}: {s.text}")
    lines.append("")
    lines.append("Return a JSON object with keys:")
    lines.append("- summary_markdown (string, markdown)")
    lines.append("- decisions (array of strings)")
    lines.append("- action_items (array of strings)")
    return "\n".join(lines)

