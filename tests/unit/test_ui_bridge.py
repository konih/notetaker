from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.domain.models import SpeakerLabel, TranscriptSegment
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import TranscriptionStatus


def _t() -> datetime:
    return datetime(2026, 5, 11, 12, 0, 0)


def test_bridge_recording_loop_enters_transcription_active() -> None:
    sid = uuid4()
    actions = application_events_to_actions(
        ev.RecordingLoopEntered(session_id=sid, audio_source="x.monitor", chunk_seconds=10, at=_t())
    )
    kinds = [type(a) for a in actions]
    assert act.AudioSourceChanged in kinds
    assert act.TranscriptionStatusChanged in kinds
    ts = next(a for a in actions if isinstance(a, act.TranscriptionStatusChanged))
    assert ts.status == TranscriptionStatus.active


def test_bridge_transcript_persisted_maps_to_segment_received() -> None:
    sid = uuid4()
    seg = TranscriptSegment(
        session_id=sid,
        started_at=_t(),
        ended_at=_t() + timedelta(seconds=1),
        text="hi",
        speaker=SpeakerLabel.speaker_2,
    )
    actions = application_events_to_actions(ev.TranscriptSegmentPersisted(segment=seg, at=_t()))
    assert len(actions) == 1
    assert isinstance(actions[0], act.TranscriptSegmentReceived)
    assert actions[0].text == "hi"
    assert actions[0].speaker == "speaker_2"


def test_bridge_recording_failed_maps_to_ui_failure() -> None:
    actions = application_events_to_actions(
        ev.RecordingFailed(session_id=None, message="x", at=_t())
    )
    assert any(isinstance(a, act.RecordingFailed) for a in actions)
