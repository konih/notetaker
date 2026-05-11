from __future__ import annotations

from datetime import datetime, timedelta

from live_meeting_transcriber.diarization.merge_service import (
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
