"""Overlap-based assignment of diarization intervals to transcript segments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from live_meeting_transcriber.domain.models import DiarizationSegment, TranscriptSegment

UNKNOWN_SPEAKER_KEY = "unknown"


def overlap_seconds(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> float:
    """Return overlap duration in seconds (0 if disjoint)."""
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    delta = (hi - lo).total_seconds()
    return max(0.0, delta)


def pick_speaker_by_overlap(
    interval_start: datetime,
    interval_end: datetime,
    diar_segments: Sequence[DiarizationSegment],
) -> str:
    """Pick the diarization ``speaker_key`` with the largest overlap with ``[interval_start, interval_end]``."""
    best_key: str | None = None
    best_ov = 0.0
    for d in diar_segments:
        ov = overlap_seconds(interval_start, interval_end, d.started_at, d.ended_at)
        if ov > best_ov:
            best_ov = ov
            best_key = d.speaker_key
    if best_key is None or best_ov <= 0.0:
        return UNKNOWN_SPEAKER_KEY
    return best_key


def merge_diarization_into_transcript_segment(
    segment: TranscriptSegment,
    diar_segments: Sequence[DiarizationSegment],
) -> TranscriptSegment:
    """Return a copy of ``segment`` with ``speaker`` set from overlap merge (or ``unknown``)."""
    key = pick_speaker_by_overlap(segment.started_at, segment.ended_at, diar_segments)
    return segment.model_copy(update={"speaker": key})
