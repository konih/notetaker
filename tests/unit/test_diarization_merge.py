from __future__ import annotations

from datetime import datetime, timedelta

from live_meeting_transcriber.diarization.merge_service import (
    exclusive_diarization_regions_for_transcription,
    merge_adjacent_diarization_segments,
    merge_diarization_into_transcript_segment,
    overlap_seconds,
    pick_speaker_by_overlap,
)
from live_meeting_transcriber.domain.models import DiarizationSegment, TranscriptSegment


def test_overlap_seconds_disjoint() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        overlap_seconds(
            t0, t0 + timedelta(seconds=1), t0 + timedelta(seconds=2), t0 + timedelta(seconds=3)
        )
        == 0.0
    )


def test_overlap_seconds_partial() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        overlap_seconds(
            t0, t0 + timedelta(seconds=10), t0 + timedelta(seconds=5), t0 + timedelta(seconds=15)
        )
        == 5.0
    )


def test_pick_speaker_largest_overlap() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    diar = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=3),
            speaker_key="speaker_1",
        ),
        DiarizationSegment(
            started_at=t0 + timedelta(seconds=3),
            ended_at=t0 + timedelta(seconds=10),
            speaker_key="speaker_2",
        ),
    ]
    assert (
        pick_speaker_by_overlap(t0 + timedelta(seconds=2), t0 + timedelta(seconds=8), diar)
        == "speaker_2"
    )


def test_pick_speaker_unknown_when_no_overlap() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    diar = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            speaker_key="speaker_1",
        ),
    ]
    assert (
        pick_speaker_by_overlap(t0 + timedelta(seconds=5), t0 + timedelta(seconds=6), diar)
        == "unknown"
    )


def test_merge_adjacent_diarization_segments_merges_same_speaker() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    segs = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            speaker_key="speaker_1",
        ),
        DiarizationSegment(
            started_at=t0 + timedelta(seconds=1),
            ended_at=t0 + timedelta(seconds=2),
            speaker_key="speaker_1",
        ),
    ]
    regions = merge_adjacent_diarization_segments(segs)
    assert regions == [(t0, t0 + timedelta(seconds=2), "speaker_1")]


def test_exclusive_timeline_prefers_narrower_turn_on_overlap() -> None:
    """Long SPEAKER_00 span that overlaps a short SPEAKER_01 burst must not swallow it."""
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    segs = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=10),
            speaker_key="speaker_1",
        ),
        DiarizationSegment(
            started_at=t0 + timedelta(seconds=2),
            ended_at=t0 + timedelta(seconds=4),
            speaker_key="speaker_2",
        ),
    ]
    regions = exclusive_diarization_regions_for_transcription(segs)
    keys_by_slice = [
        ((r[0] - t0).total_seconds(), (r[1] - t0).total_seconds(), r[2]) for r in regions
    ]
    assert [x[2] for x in keys_by_slice] == ["speaker_1", "speaker_2", "speaker_1"]
    assert keys_by_slice[0][:2] == (0.0, 2.0)
    assert keys_by_slice[1][:2] == (2.0, 4.0)
    assert keys_by_slice[2][:2] == (4.0, 10.0)


def test_merge_adjacent_diarization_segments_keeps_distinct_speakers() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    segs = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=3),
            speaker_key="speaker_1",
        ),
        DiarizationSegment(
            started_at=t0 + timedelta(seconds=3),
            ended_at=t0 + timedelta(seconds=10),
            speaker_key="speaker_2",
        ),
    ]
    regions = merge_adjacent_diarization_segments(segs)
    assert len(regions) == 2
    assert regions[0][2] == "speaker_1"
    assert regions[1][2] == "speaker_2"


def test_merge_transcript_segment() -> None:
    sid = __import__("uuid").uuid4()
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    seg = TranscriptSegment(
        session_id=sid,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=5),
        text="hello",
        speaker="unknown",
    )
    diar = [
        DiarizationSegment(
            started_at=t0,
            ended_at=t0 + timedelta(seconds=5),
            speaker_key="speaker_3",
        ),
    ]
    out = merge_diarization_into_transcript_segment(seg, diar)
    assert out.speaker == "speaker_3"
    assert out.text == "hello"
