"""F6 — richer live speaker UX: per-speaker recency in the Live sidebar.

With live diarization off by default, the honest signal is the transcript
segments that DO carry speakers (dual-path stereo: YOU / REMOTE, plus offline
labels on resume). The sidebar's "heard:" list gains a compact last-active age
per speaker, most recent first, so the operator can see who talked when.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import TranscriptLineState, initial_app_state
from live_meeting_transcriber.ui.state.reducer import reduce
from live_meeting_transcriber.ui.state.selectors import build_pipeline_card_lines

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _segment_action(speaker: str, ended_at: datetime) -> act.TranscriptSegmentReceived:
    return act.TranscriptSegmentReceived(
        segment_id=str(uuid4()),
        session_id=str(uuid4()),
        started_at=ended_at,
        ended_at=ended_at,
        text="hi",
        speaker=speaker,
        at=ended_at,
    )


def test_reducer_tracks_speaker_last_active() -> None:
    state = reduce(initial_app_state(), _segment_action("YOU", _NOW))
    assert state.speaker_last_active == {"YOU": _NOW}
    later = _NOW + timedelta(seconds=30)
    state = reduce(state, _segment_action("YOU", later))
    assert state.speaker_last_active == {"YOU": later}


def test_reducer_ignores_unknown_and_empty_speakers() -> None:
    state = reduce(initial_app_state(), _segment_action("unknown", _NOW))
    state = reduce(state, _segment_action("", _NOW))
    assert state.speaker_last_active == {}


def test_recording_start_resets_recency_and_resume_seeds_it() -> None:
    state = reduce(initial_app_state(), _segment_action("YOU", _NOW))
    fresh = reduce(
        state,
        act.RecordingStarted(
            session_id=uuid4(),
            title="t",
            audio_source="s",
            microphone_source=None,
            chunk_seconds=10,
            at=_NOW,
        ),
    )
    assert fresh.speaker_last_active == {}

    loaded = (
        TranscriptLineState(
            id=str(uuid4()),
            session_id=str(uuid4()),
            started_at=_NOW - timedelta(minutes=10),
            ended_at=_NOW - timedelta(minutes=9),
            text="earlier",
            speaker="REMOTE",
        ),
    )
    resumed = reduce(
        state,
        act.RecordingStarted(
            session_id=uuid4(),
            title="t",
            audio_source="s",
            microphone_source=None,
            chunk_seconds=10,
            at=_NOW,
            resumed=True,
            loaded_transcript_segments=loaded,
        ),
    )
    assert resumed.speaker_last_active == {"REMOTE": _NOW - timedelta(minutes=9)}


def test_speakers_line_shows_compact_recency_most_recent_first() -> None:
    state = initial_app_state().model_copy(
        update={
            "diarization_detected_speakers": frozenset({"YOU", "REMOTE"}),
            "speaker_last_active": {
                "REMOTE": _NOW - timedelta(minutes=5),
                "YOU": _NOW - timedelta(seconds=3),
            },
        }
    )
    speakers_line = next(
        line for line in build_pipeline_card_lines(state, _NOW) if "Speakers" in line
    )
    assert "YOU now" in speakers_line
    assert "REMOTE 5m" in speakers_line
    assert speakers_line.index("YOU") < speakers_line.index("REMOTE")  # most recent first


def test_speakers_without_recency_still_listed() -> None:
    state = initial_app_state().model_copy(
        update={"diarization_detected_speakers": frozenset({"SPEAKER_00"})}
    )
    speakers_line = next(
        line for line in build_pipeline_card_lines(state, _NOW) if "Speakers" in line
    )
    assert "SPEAKER_00" in speakers_line
