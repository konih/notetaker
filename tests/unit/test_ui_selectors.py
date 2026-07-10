from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    TranscriptionStatus,
    TranscriptLineState,
    UiErrorState,
)
from live_meeting_transcriber.ui.state.selectors import (
    select_decayed_level,
    select_display_speaker,
    select_elapsed_label,
    select_header_title,
    select_is_recording,
    select_level_bar,
    select_status_line,
    select_transcript_timestamp,
    select_unacknowledged_errors,
)
from live_meeting_transcriber.utils.time import utc_now

PLUS2 = timezone(timedelta(hours=2))


def _line(**over: object) -> TranscriptLineState:
    base: dict[str, object] = dict(
        id="1",
        session_id="s",
        started_at=datetime(2026, 7, 8, 9, 14, 0, tzinfo=UTC),
        ended_at=datetime(2026, 7, 8, 9, 14, 8, tzinfo=UTC),
        text="hello",
        speaker="speaker_0",
    )
    base.update(over)
    return TranscriptLineState(**base)  # type: ignore[arg-type]


def test_select_transcript_timestamp_is_compact_local_clock() -> None:
    # Was a full ISO range ("2026-07-08T09:14:00 → ...09:14:08"); now a compact local clock.
    assert select_transcript_timestamp(_line(), tz=PLUS2) == "11:14:00"


_INTERNAL_KEYS = ("rec=", "asr=", "live_spk=", "diar_ui=", "src=", "heard=")


def test_status_line_recording_uses_plain_language_not_internal_keys() -> None:
    s = AppState(
        recording_status=RecordingStatus.recording,
        transcription_status=TranscriptionStatus.active,
    )
    line = select_status_line(s)
    assert "Recording" in line
    assert "transcribing" in line.lower()
    for key in _INTERNAL_KEYS:
        assert key not in line


def test_status_line_idle_is_plain() -> None:
    assert "Idle" in select_status_line(AppState(recording_status=RecordingStatus.idle))


def test_status_line_dual_channel_names_you_and_remote() -> None:
    s = AppState(
        recording_status=RecordingStatus.recording,
        audio_channels=2,
        audio_stereo_mode="dual_path",
    )
    line = select_status_line(s).lower()
    assert "you" in line and "remote" in line


def test_status_line_mono_is_single_channel() -> None:
    line = select_status_line(AppState(audio_channels=1)).lower()
    assert "single channel" in line


def test_status_line_omits_heard_speakers_to_avoid_duplication() -> None:
    # "heard" speakers live on the dedicated Live-speakers sidebar line, not here (no duplicate).
    s = AppState(
        recording_status=RecordingStatus.recording,
        diarization_detected_speakers=frozenset({"speaker_0", "speaker_1"}),
    )
    assert "heard" not in select_status_line(s).lower()


def test_status_line_surfaces_transcription_failure() -> None:
    s = AppState(
        recording_status=RecordingStatus.recording,
        transcription_status=TranscriptionStatus.failed,
    )
    assert "failed" in select_status_line(s).lower()


def test_select_elapsed_label_while_recording() -> None:
    start = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    s = AppState(recording_status=RecordingStatus.recording, recording_started_at=start)
    now = start + timedelta(seconds=65)
    assert select_elapsed_label(s, now) == "01:05"


def test_select_elapsed_label_none_when_not_recording() -> None:
    start = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    s = AppState(recording_status=RecordingStatus.stopped, recording_started_at=start)
    assert select_elapsed_label(s, start + timedelta(seconds=65)) is None


def test_select_elapsed_label_none_without_start() -> None:
    s = AppState(recording_status=RecordingStatus.recording, recording_started_at=None)
    assert select_elapsed_label(s, datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)) is None


def test_select_elapsed_label_handles_naive_start_without_crashing() -> None:
    # A legacy/naive recording_started_at (see A11) must not crash the per-second timer:
    # a raw aware-minus-naive subtraction would raise TypeError. Naive is treated as UTC.
    naive_start = datetime(2026, 7, 8, 12, 0, 0)
    s = AppState(recording_status=RecordingStatus.recording, recording_started_at=naive_start)
    now = datetime(2026, 7, 8, 12, 0, 30, tzinfo=UTC)
    assert select_elapsed_label(s, now) == "00:30"


def test_select_header_title_uses_session_title() -> None:
    s = AppState(session_title="Sync")
    assert select_header_title(s) == "Sync"


def test_select_header_title_shows_recording_glyph() -> None:
    s = AppState(session_title="Meet", recording_status=RecordingStatus.recording)
    assert select_header_title(s).startswith("⏺")
    assert "Meet" in select_header_title(s)


def test_select_is_recording() -> None:
    assert select_is_recording(AppState(recording_status=RecordingStatus.recording)) is True
    assert select_is_recording(AppState(recording_status=RecordingStatus.idle)) is False


def test_select_unacknowledged_errors() -> None:
    e1 = UiErrorState(id="1", message="a", at=utc_now(), acknowledged=False)
    e2 = UiErrorState(id="2", message="b", at=utc_now(), acknowledged=True)
    s = AppState(recent_errors=(e1, e2))
    assert [e.id for e in select_unacknowledged_errors(s)] == ["1"]


def test_select_display_speaker_alias() -> None:
    s = AppState(speaker_aliases={"speaker_1": "Alice"})
    assert select_display_speaker(s, "speaker_1") == "Alice"
    assert select_display_speaker(s, "speaker_2") == "Speaker 2"


def test_select_display_speaker_unknown() -> None:
    s = AppState()
    assert select_display_speaker(s, "unknown") == "Unknown Speaker"


def test_select_level_bar() -> None:
    assert "—" in select_level_bar(AppState(current_level_meter=None))
    b = select_level_bar(AppState(current_level_meter=0.5), width=4)
    assert "█" in b
    assert "░" in b


def test_select_decayed_level_holds_one_interval_then_falls_off() -> None:
    # U13: peak-hold with delayed decay. The per-chunk peak is held for one chunk
    # interval so continuous speech does NOT pulse full->empty between updates; it only
    # decays once a chunk is late (real silence / stalled capture / stopped session).
    t0 = utc_now()
    s = AppState(
        recording_status=RecordingStatus.recording,
        current_level_meter=0.8,
        last_level_at=t0,
        chunk_seconds=10,
    )
    assert select_decayed_level(s, t0) == 0.8  # fresh reading: full peak
    assert select_decayed_level(s, t0 + timedelta(seconds=8)) == 0.8  # held: no mid-chunk pulse
    mid = select_decayed_level(s, t0 + timedelta(seconds=15))  # a chunk is late -> decaying
    assert mid is not None and 0.3 < mid < 0.5
    # Two intervals stale: floored at zero rather than a frozen peak.
    assert select_decayed_level(s, t0 + timedelta(seconds=25)) == 0.0


def test_select_decayed_level_none_when_idle_or_unset() -> None:
    # A stopped/idle session must not keep showing a stale peak.
    now = utc_now()
    idle = AppState(current_level_meter=0.9, last_level_at=now)
    assert select_decayed_level(idle, now) is None
    no_reading = AppState(recording_status=RecordingStatus.recording, current_level_meter=None)
    assert select_decayed_level(no_reading, now) is None


def test_select_level_bar_decays_with_now() -> None:
    t0 = utc_now()
    s = AppState(
        recording_status=RecordingStatus.recording,
        current_level_meter=1.0,
        last_level_at=t0,
        chunk_seconds=10,
    )
    fresh = select_level_bar(s, t0, width=10)
    stale = select_level_bar(s, t0 + timedelta(seconds=18), width=10)  # past hold, decaying
    assert fresh.count("█") > stale.count("█")  # decayed reading => fewer filled blocks
    # Passing no clock keeps the legacy (non-decaying) behaviour for callers that
    # don't have a wall clock handy.
    assert "█" in select_level_bar(s, width=4)


def test_select_header_fallback_uuid_session() -> None:
    sid = uuid4()
    s = AppState(current_session_id=sid, session_title=None)
    assert select_header_title(s) == "No session"
