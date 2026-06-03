"""Format stored transcript segments for the Meetings tab detail view."""

from __future__ import annotations

from datetime import datetime

from live_meeting_transcriber.application.slide_review import format_timestamp
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.speaker_display import format_transcript_speaker_label


def segment_offset_seconds(segment: TranscriptSegment, session_started_at: datetime) -> float:
    """Elapsed seconds from session start to the segment start."""
    return max(0.0, (segment.started_at - session_started_at).total_seconds())


def format_segment_timestamp(segment: TranscriptSegment, session_started_at: datetime) -> str:
    """Bracketed offset timestamp, e.g. ``[1:05]`` or ``[1:01:01]``."""
    return f"[{format_timestamp(segment_offset_seconds(segment, session_started_at))}]"


def format_meeting_transcript_line(
    segment: TranscriptSegment,
    session_started_at: datetime,
    name_map: dict[str, str] | None = None,
) -> str:
    """One scrollable line: ``[MM:SS] Speaker: text``."""
    ts = format_segment_timestamp(segment, session_started_at)
    label = format_transcript_speaker_label(segment.speaker, name_map)
    text = segment.text.replace("\n", " ").strip()
    return f"{ts} {label}: {text}"


def format_meeting_transcript_text(
    segments: list[TranscriptSegment],
    session: MeetingSession,
    name_map: dict[str, str] | None = None,
) -> str:
    """Full meeting transcript for read-only display widgets."""
    if not segments:
        return "— No transcript segments yet. —"
    lines = [
        format_meeting_transcript_line(segment, session.started_at, name_map)
        for segment in segments
    ]
    return "\n".join(lines)
