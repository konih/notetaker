"""Redesign — pure renderers for the status deck, VU meter, and transcript.

Everything asserted here is a deterministic function of its inputs; no Textual
app is mounted. Visual glyph details are asserted loosely (presence/zones),
exact widths and determinism strictly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from live_meeting_transcriber.ui.state.model import RecordingStatus, initial_app_state
from live_meeting_transcriber.ui.tui.rendering import (
    build_deck_markup,
    sparkline_markup,
    speaker_color,
    state_pill_markup,
    transcript_segment_text,
    vu_bar_markup,
)
from live_meeting_transcriber.ui.tui.theme import (
    LEVEL_HOT,
    LEVEL_OK,
    LEVEL_PEAK,
    SPEAKER_PALETTE,
)
from rich.text import Text
from textual.content import Content

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _plain(markup: str) -> str:
    return Content.from_markup(markup).plain


# --- VU bar -----------------------------------------------------------------


def test_vu_bar_has_fixed_width_at_any_level() -> None:
    for level in (None, 0.0, 0.33, 0.5, 0.87, 1.0, 2.0):
        assert len(_plain(vu_bar_markup(level, width=14))) == 14


def test_vu_bar_idle_is_dim_empty_track() -> None:
    markup = vu_bar_markup(None, width=10)
    assert "dim" in markup
    assert "█" not in markup


def test_vu_bar_zones_color_by_position() -> None:
    # A full bar crosses all three zones: green base, amber, red peak cells.
    markup = vu_bar_markup(1.0, width=20)
    assert LEVEL_OK in markup
    assert LEVEL_HOT in markup
    assert LEVEL_PEAK in markup
    # A quiet level stays entirely in the green zone.
    quiet = vu_bar_markup(0.3, width=20)
    assert LEVEL_OK in quiet
    assert LEVEL_HOT not in quiet
    assert LEVEL_PEAK not in quiet


def test_vu_bar_fills_monotonically_with_level() -> None:
    def filled(markup: str) -> int:
        return sum(1 for ch in _plain(markup) if ch != "╌")

    levels = [0.1, 0.4, 0.7, 1.0]
    counts = [filled(vu_bar_markup(lv, width=16)) for lv in levels]
    assert counts == sorted(counts)
    assert counts[0] >= 1


# --- sparkline ----------------------------------------------------------------


def test_sparkline_fixed_width_and_right_aligned() -> None:
    markup = sparkline_markup([0.2, 0.9], width=8)
    plain = _plain(markup)
    assert len(plain) == 8
    # History grows in from the right: the newest (loud) reading is last.
    assert plain[-1] == "█"


def test_sparkline_empty_history_renders_flat_dim_baseline() -> None:
    markup = sparkline_markup([], width=6)
    assert _plain(markup) == "▁" * 6
    assert "dim" in markup


def test_sparkline_columns_zone_colored_by_value() -> None:
    markup = sparkline_markup([0.1, 0.95], width=2)
    assert LEVEL_OK in markup
    assert LEVEL_PEAK in markup


# --- state pill ---------------------------------------------------------------


def test_state_pill_recording_pulses() -> None:
    on = state_pill_markup(RecordingStatus.recording, pulse_on=True)
    off = state_pill_markup(RecordingStatus.recording, pulse_on=False)
    assert on != off
    assert "REC" in _plain(on) and "REC" in _plain(off)


def test_state_pill_covers_every_status() -> None:
    for status in RecordingStatus:
        plain = _plain(state_pill_markup(status))
        assert plain.strip(), f"empty pill for {status}"


def test_state_pill_idle_is_quiet_not_filled() -> None:
    markup = state_pill_markup(RecordingStatus.idle)
    assert "dim" in markup
    assert " on " not in markup  # no filled background when idle


# --- speaker colors -----------------------------------------------------------


def test_speaker_color_is_stable_and_from_palette() -> None:
    first = speaker_color("speaker_0")
    assert first == speaker_color("speaker_0")
    assert first in SPEAKER_PALETTE
    # Not all keys collapse onto one palette slot.
    colors = {speaker_color(f"speaker_{i}") for i in range(8)}
    assert len(colors) > 1


# --- transcript block ----------------------------------------------------------


def test_transcript_segment_is_markup_safe() -> None:
    hostile = "we said [bold]this[/] and [red]that[/]"
    text = transcript_segment_text(
        timestamp="12:00:00", speaker_label="Alice", speaker_key="speaker_0", body=hostile
    )
    assert isinstance(text, Text)
    # The hostile brackets survive verbatim as content, not styling.
    assert "[bold]this[/]" in text.plain
    assert "Alice" in text.plain
    assert "12:00:00" in text.plain


def test_transcript_segment_colors_match_speaker_key() -> None:
    text = transcript_segment_text(
        timestamp="12:00:00", speaker_label="Alice", speaker_key="speaker_3", body="hi"
    )
    expected = speaker_color("speaker_3")
    spans = " ".join(str(span.style) for span in text.spans)
    assert expected in spans


# --- deck line ------------------------------------------------------------------


def test_deck_idle_shows_pill_and_placeholder_title_only() -> None:
    state = initial_app_state()
    plain = _plain(build_deck_markup(state, _NOW))
    assert "IDLE" in plain
    assert "no session" in plain
    assert "⏱" not in plain  # no elapsed when idle
    assert "█" not in plain  # no meter when idle


def test_deck_recording_shows_elapsed_meter_and_sparkline() -> None:
    state = initial_app_state().model_copy(
        update={
            "recording_status": RecordingStatus.recording,
            "session_title": "Team sync",
            "recording_started_at": _NOW - timedelta(seconds=125),
            "current_level_meter": 0.5,
            "last_level_at": _NOW,
            "level_history": (0.2, 0.5),
        }
    )
    markup = build_deck_markup(state, _NOW, pulse_on=True)
    plain = _plain(markup)
    assert "REC" in plain
    assert "Team sync" in plain
    assert "02:05" in plain
    assert "50%" in plain


def test_deck_title_with_markup_chars_is_escaped() -> None:
    state = initial_app_state().model_copy(update={"session_title": "Q3 [budget] review"})
    plain = _plain(build_deck_markup(state, _NOW))
    assert "Q3 [budget] review" in plain
