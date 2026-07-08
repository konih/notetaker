from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    TranscriptLineState,
    UiErrorState,
)
from live_meeting_transcriber.ui.state.selectors import (
    select_display_speaker,
    select_header_title,
    select_is_recording,
    select_level_bar,
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


def test_select_header_fallback_uuid_session() -> None:
    sid = uuid4()
    s = AppState(current_session_id=sid, session_title=None)
    assert select_header_title(s) == "No session"
