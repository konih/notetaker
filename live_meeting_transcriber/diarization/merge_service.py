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


def merge_adjacent_diarization_segments(
    segments: Sequence[DiarizationSegment],
) -> list[tuple[datetime, datetime, str]]:
    """Merge overlapping / touching intervals that share the same ``speaker_key`` (time order).

    .. note::

        If pyannote returns **overlapping** turns for different speakers, this can leave
        long intervals that still cover other speakers' time. Prefer
        :func:`exclusive_diarization_regions_for_transcription` for per-region ASR.
    """
    if not segments:
        return []
    ordered = sorted(segments, key=lambda d: (d.started_at, d.ended_at))
    cur_s, cur_e, cur_k = ordered[0].started_at, ordered[0].ended_at, ordered[0].speaker_key
    out: list[tuple[datetime, datetime, str]] = []
    gap_merge_seconds = 0.05

    for d in ordered[1:]:
        gap = (d.started_at - cur_e).total_seconds()
        if (d.speaker_key == cur_k and gap <= gap_merge_seconds) or (
            d.speaker_key == cur_k and d.started_at <= cur_e
        ):
            cur_e = max(cur_e, d.ended_at)
        else:
            out.append((cur_s, cur_e, cur_k))
            cur_s, cur_e, cur_k = d.started_at, d.ended_at, d.speaker_key
    out.append((cur_s, cur_e, cur_k))
    return out


def _merge_touching_same_speaker(
    regions: list[tuple[datetime, datetime, str]],
    *,
    gap_merge_seconds: float = 0.05,
) -> list[tuple[datetime, datetime, str]]:
    if not regions:
        return []
    cur_s, cur_e, cur_k = regions[0]
    out: list[tuple[datetime, datetime, str]] = []
    for t0, t1, k in regions[1:]:
        gap = (t0 - cur_e).total_seconds()
        if k == cur_k and (gap <= gap_merge_seconds or t0 <= cur_e):
            cur_e = max(cur_e, t1)
        else:
            out.append((cur_s, cur_e, cur_k))
            cur_s, cur_e, cur_k = t0, t1, k
    out.append((cur_s, cur_e, cur_k))
    return out


def exclusive_diarization_regions_for_transcription(
    segments: Sequence[DiarizationSegment],
) -> list[tuple[datetime, datetime, str]]:
    """Non-overlapping timeline for per-region transcription.

    Splits the union timeline at every diarization boundary, assigns each elementary
    slice to the speaker whose original interval overlaps that slice the most (ties:
    lexicographically smaller ``speaker_key``). Then merges adjacent slices with the
    same speaker so ASR runs once per contiguous same-speaker run.

    This avoids attributing an entire overlapping ``speaker_1`` span to one transcript
    when another speaker holds part of that time range.
    """
    if not segments:
        return []
    bounds_set: set[datetime] = set()
    for d in segments:
        bounds_set.add(d.started_at)
        bounds_set.add(d.ended_at)
    bounds = sorted(bounds_set)
    raw: list[tuple[datetime, datetime, str]] = []
    for i in range(len(bounds) - 1):
        t0, t1 = bounds[i], bounds[i + 1]
        if t1 <= t0:
            continue
        slice_dur = (t1 - t0).total_seconds()
        if slice_dur <= 0:
            continue
        best_key: str | None = None
        best_ov = -1.0
        best_span: float | None = None
        for d in segments:
            ov = overlap_seconds(t0, t1, d.started_at, d.ended_at)
            if ov <= 0:
                continue
            span = (d.ended_at - d.started_at).total_seconds()
            if ov > best_ov + 1e-9:
                best_ov = ov
                best_key = d.speaker_key
                best_span = span
            elif abs(ov - best_ov) < 1e-9 and best_key is not None and best_span is not None:
                if span < best_span - 1e-9:
                    best_key = d.speaker_key
                    best_span = span
                elif abs(span - best_span) < 1e-9 and d.speaker_key < best_key:
                    best_key = d.speaker_key
        if best_key is None:
            continue
        raw.append((t0, t1, best_key))
    return _merge_touching_same_speaker(raw)
