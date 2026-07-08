from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    AppState,
    DiarizationStatus,
    RecordingStatus,
    SessionRowState,
    TranscriptionStatus,
    TranscriptLineState,
    initial_app_state,
)
from live_meeting_transcriber.ui.state.reducer import reduce


def _t() -> datetime:
    return datetime(2026, 5, 11, 12, 0, 0)


def test_settings_loaded_updates_config_fields() -> None:
    s0 = initial_app_state()
    s1 = reduce(
        s0,
        act.SettingsLoaded(
            transcription_provider="openai",
            transcription_model="m1",
            summarization_provider="openai",
            summary_model="m2",
            database_url="sqlite:////tmp/x.db",
            audio_chunk_seconds=15,
            audio_sample_rate=16000,
            audio_channels=1,
            audio_stereo_mode="mixdown",
            diarization_enabled=True,
            diarization_provider="noop",
            finalize_on_session_stop=False,
            whisperx_model="large-v3-turbo",
            whisperx_skip_alignment=False,
            hf_token_configured=False,
            log_file_resolved="/tmp/app.log",
            audio_include_microphone=True,
            at=_t(),
        ),
    )
    assert s1.transcription_model == "m1"
    assert s1.summary_model == "m2"
    assert s1.database_url == "sqlite:////tmp/x.db"
    assert s1.chunk_seconds == 15
    assert s1.diarization_enabled is True
    assert s1.diarization_status == DiarizationStatus.disabled
    assert s1.log_file_path == "/tmp/app.log"


def test_recording_lifecycle() -> None:
    s0 = initial_app_state()
    sid = uuid4()
    s1 = reduce(
        s0,
        act.RecordingStartRequested(title="T", audio_source="sink.monitor", at=_t()),
    )
    assert s1.recording_status == RecordingStatus.starting
    assert s1.session_title == "T"

    s2 = reduce(
        s1,
        act.RecordingStarted(
            session_id=sid,
            title="T",
            audio_source="sink.monitor",
            microphone_source="mic",
            chunk_seconds=10,
            at=_t(),
        ),
    )
    assert s2.recording_status == RecordingStatus.recording
    assert s2.transcription_status == TranscriptionStatus.active
    assert s2.current_session_id == sid
    assert s2.microphone_source == "mic"
    assert s2.recent_transcript_segments == ()

    s3 = reduce(s2, act.RecordingStopRequested(at=_t()))
    assert s3.recording_status == RecordingStatus.stopping

    s4 = reduce(s3, act.RecordingStopped(at=_t()))
    assert s4.recording_status == RecordingStatus.stopped
    assert s4.transcription_status == TranscriptionStatus.idle


def test_recording_started_at_set_on_start_and_cleared_on_stop() -> None:
    s0 = initial_app_state()
    assert s0.recording_started_at is None
    started = reduce(
        s0,
        act.RecordingStarted(
            session_id=uuid4(),
            title="T",
            audio_source="sink.monitor",
            microphone_source=None,
            chunk_seconds=10,
            at=_t(),
        ),
    )
    assert started.recording_started_at == _t()
    stopped = reduce(started, act.RecordingStopped(at=_t() + timedelta(seconds=42)))
    assert stopped.recording_started_at is None


def test_recording_started_at_cleared_on_failure() -> None:
    s0 = reduce(
        initial_app_state(),
        act.RecordingStarted(
            session_id=uuid4(),
            title="T",
            audio_source="sink.monitor",
            microphone_source=None,
            chunk_seconds=10,
            at=_t(),
        ),
    )
    failed = reduce(s0, act.RecordingFailed(message="boom", at=_t()))
    assert failed.recording_started_at is None


def test_recording_stop_ignored_when_idle() -> None:
    s0 = initial_app_state()
    s1 = reduce(s0, act.RecordingStopRequested(at=_t()))
    assert s1.recording_status == RecordingStatus.idle


def test_transcript_segment_appends_and_trims() -> None:
    s0 = initial_app_state()
    sid = str(uuid4())
    t0 = _t()
    for i in range(3):
        s0 = reduce(
            s0,
            act.TranscriptSegmentReceived(
                segment_id=f"id-{i}",
                session_id=sid,
                started_at=t0 + timedelta(seconds=i),
                ended_at=t0 + timedelta(seconds=i + 1),
                text=f"L{i}",
                speaker="unknown",
                at=t0,
            ),
        )
    assert len(s0.recent_transcript_segments) == 3
    assert s0.recent_transcript_segments[-1].text == "L2"


def test_diarization_segment_updates_speaker() -> None:
    sid = str(uuid4())
    t0 = _t()
    s0 = reduce(
        initial_app_state(),
        act.TranscriptSegmentReceived(
            segment_id="seg-1",
            session_id=sid,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=1),
            text="hello",
            speaker="unknown",
            at=t0,
        ),
    )
    s1 = reduce(
        s0,
        act.DiarizationSegmentReceived(segment_id="seg-1", speaker="speaker_1", at=t0),
    )
    assert s1.recent_transcript_segments[0].speaker == "speaker_1"


def test_speaker_alias_updated() -> None:
    s0 = reduce(
        initial_app_state(),
        act.SpeakerAliasUpdated(speaker_key="speaker_1", alias="Alice", at=_t()),
    )
    assert s0.speaker_aliases["speaker_1"] == "Alice"


def test_recording_started_resumed_keeps_loaded_transcript() -> None:
    sid = uuid4()
    sid_str = str(sid)
    t0 = _t()
    existing = TranscriptLineState(
        id="seg-1",
        session_id=sid_str,
        started_at=t0,
        ended_at=t0 + timedelta(seconds=1),
        text="before crash",
        speaker="YOU",
    )
    s0 = AppState(
        current_session_id=sid,
        session_title="Standup",
        recording_status=RecordingStatus.failed,
        recent_transcript_segments=(existing,),
    )
    s1 = reduce(
        s0,
        act.RecordingStarted(
            session_id=sid,
            title="Standup",
            audio_source="sink.monitor",
            microphone_source="mic",
            chunk_seconds=10,
            at=_t(),
            resumed=True,
            loaded_transcript_segments=(existing,),
        ),
    )
    assert s1.recording_status == RecordingStatus.recording
    assert len(s1.recent_transcript_segments) == 1
    assert s1.recent_transcript_segments[0].text == "before crash"
    assert s1.diarization_detected_speakers == frozenset({"YOU"})


def test_recording_failed_appends_error() -> None:
    s0 = reduce(
        initial_app_state(),
        act.RecordingFailed(message="boom", at=_t()),
    )
    assert s0.recording_status == RecordingStatus.failed
    assert s0.transcription_status == TranscriptionStatus.failed
    assert len(s0.recent_errors) == 1
    assert s0.recent_errors[0].message == "boom"


def test_error_acknowledged() -> None:
    s0 = reduce(initial_app_state(), act.ErrorRaised(message="e1", at=_t()))
    eid = s0.recent_errors[0].id
    s1 = reduce(s0, act.ErrorAcknowledged(error_id=eid, at=_t()))
    assert s1.recent_errors[0].acknowledged is True


def test_sessions_list_loaded() -> None:
    sid = str(uuid4())
    row = SessionRowState(
        id=sid,
        title="A",
        started_at=_t(),
        ended_at=None,
    )
    s0 = reduce(
        initial_app_state(),
        act.SessionsListLoaded(rows=(row,), at=_t()),
    )
    assert len(s0.sessions_catalog) == 1
    assert s0.sessions_loading is False


def test_session_title_updated() -> None:
    sid = uuid4()
    row = SessionRowState(
        id=str(sid),
        title="Old",
        started_at=_t(),
        ended_at=None,
    )
    s0 = AppState(sessions_catalog=(row,), current_session_id=sid, session_title="Old")
    s1 = reduce(s0, act.SessionTitleUpdated(session_id=sid, title="New", at=_t()))
    assert s1.sessions_catalog[0].title == "New"
    assert s1.session_title == "New"


def test_notice_raised_appends() -> None:
    s0 = initial_app_state()
    s1 = reduce(s0, act.NoticeRaised(message="Exported to /tmp/x.md", at=_t()))
    assert s1.notices[-1] == "Exported to /tmp/x.md"


def test_settings_screen_toggle() -> None:
    s0 = reduce(initial_app_state(), act.SettingsScreenOpened(at=_t()))
    assert s0.settings_screen_open is True
    s1 = reduce(s0, act.SettingsScreenClosed(at=_t()))
    assert s1.settings_screen_open is False


def test_finalize_session_succeeded_sets_pending_and_optional_live_lines() -> None:
    sid = uuid4()
    sid_str = str(sid)
    line = TranscriptLineState(
        id="seg-1",
        session_id=sid_str,
        started_at=_t(),
        ended_at=_t(),
        text="hello",
        speaker="SPEAKER_00",
    )
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=3,
            live_lines=(line,),
            at=_t(),
        ),
    )
    assert s0.pending_meeting_detail_reload == sid
    assert s0.recent_transcript_segments == (line,)
    assert "3 segment" in s0.notices[-1]


def test_finalize_session_succeeded_without_live_lines() -> None:
    sid = uuid4()
    s0 = initial_app_state()
    s1 = reduce(
        s0,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=1,
            live_lines=None,
            at=_t(),
        ),
    )
    assert s1.pending_meeting_detail_reload == sid
    assert s1.recent_transcript_segments == s0.recent_transcript_segments


def test_detail_reload_acknowledged_clears_pending() -> None:
    sid = uuid4()
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=1,
            live_lines=None,
            at=_t(),
        ),
    )
    s1 = reduce(s0, act.DetailReloadAcknowledged(at=_t()))
    assert s1.pending_meeting_detail_reload is None


def test_error_raised_appends_ui_log_line() -> None:
    s0 = reduce(
        initial_app_state(),
        act.ErrorRaised(message="something broke", at=_t()),
    )
    assert len(s0.ui_log_lines) == 1
    assert "something broke" in s0.ui_log_lines[0]


def test_ui_log_line_added_appends() -> None:
    s0 = reduce(
        initial_app_state(),
        act.UiLogLineAdded(level="info", message="step one", at=_t()),
    )
    assert len(s0.ui_log_lines) == 1
    s1 = reduce(
        s0,
        act.UiLogLineAdded(level="info", message="step two", at=_t()),
    )
    assert len(s1.ui_log_lines) == 2
