from __future__ import annotations

from collections.abc import Iterable

from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label
from live_meeting_transcriber.obsidian.vault_patterns import VaultNamingHints


def build_summary_prompt(
    *,
    session: MeetingSession,
    segments: Iterable[TranscriptSegment],
    speaker_display: dict[str, str] | None = None,
    user_context: str | None = None,
    vault_hints: VaultNamingHints | None = None,
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
    if user_context and user_context.strip():
        lines.append("")
        lines.append("Additional context from the user (for this summary only):")
        lines.append(user_context.strip())
    lines.append("")
    lines.append("Transcript (chronological):")
    for s in segments:
        # Avoid leaking provider metadata; only use text and coarse timestamps.
        label = format_transcript_speaker_label(s.speaker, disp)
        lines.append(f"- [{s.started_at.isoformat()} → {s.ended_at.isoformat()}] {label}: {s.text}")
    lines.append("")
    if vault_hints and vault_hints.sample_titles:
        lines.append(
            "Existing vault meeting title examples (match this style when proposing a title):"
        )
        for title in vault_hints.sample_titles:
            lines.append(f"- {title}")
        lines.append("")
    if vault_hints and vault_hints.common_tags:
        lines.append(
            "Common tags in this vault (lowercase, hyphenated): "
            + ", ".join(vault_hints.common_tags)
        )
        lines.append("")
    lines.append("Return a JSON object with keys:")
    lines.append("- summary_markdown (string, markdown with concise bullets under ## Summary)")
    lines.append("- decisions (array of strings)")
    lines.append("- action_items (array of strings)")
    lines.append("- metadata (object, optional) with:")
    lines.append("  - title: short descriptive meeting title")
    lines.append("  - topic: one-line topic for Obsidian frontmatter")
    lines.append("  - tags: array of lowercase tag strings (include meeting)")
    lines.append("  - participants: array of participant display names from the transcript")
    lines.append("  - series: recurring series name when clearly a standup/sync/review series")
    lines.append("  - location: e.g. Microsoft Teams when mentioned")
    lines.append('  - related: optional Obsidian wikilink string e.g. "[[Project]]"')
    lines.append(
        "  - confidence: object mapping metadata field names to boolean "
        "(true only when clearly supported by the transcript)"
    )
    return "\n".join(lines)
