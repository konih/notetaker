"""F8 — progress UI for diarization / chunk processing / time-to-next-chunk.

B7 already ships the finalize lifecycle (queued/started/stage/outcome) into the
always-visible status deck as *text*. F8's remainder, pinned here:

1. The deck's finalize segment upgrades from bare stage text to a **stage-progress
   bar** derived from the WhisperX pipeline stage sequence
   (load → transcribe → align → diarize → persist).
2. The Live tab shows **per-chunk transcription progress** (chunk N transcribing /
   done) on the existing Audio card "Chunk" line — no new panel (U8 density).
3. The same line carries a **next-chunk countdown** computed purely from the last
   chunk timestamp + ``audio_chunk_seconds``, advanced by the existing 1s tick.

Everything asserted here is a pure function of ``AppState`` (+ wall clock), per
house style; one Pilot test proves the bar reaches the real deck widget.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    AppState,
    RecordingStatus,
    initial_app_state,
)
from live_meeting_transcriber.ui.state.reducer import reduce
from live_meeting_transcriber.ui.state.selectors import (
    FINALIZE_STAGES,
    build_audio_card_lines,
    select_chunk_progress_label,
    select_finalize_stage_index,
    select_next_chunk_eta_seconds,
)
from live_meeting_transcriber.ui.tui.rendering import (
    finalize_deck_markup,
    stage_bar_markup,
)
from rich.markup import render as render_markup

from tests.unit.conftest import make_mock_tui_container, make_tui_harness

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _plain(markup: str) -> str:
    """Visible text of a Rich markup string (tags stripped)."""
    return render_markup(markup).plain


def _recording_state(**overrides: object) -> AppState:
    base = initial_app_state().model_copy(
        update={
            "recording_status": RecordingStatus.recording,
            "recording_started_at": _NOW,
            "chunk_seconds": 10,
        }
    )
    return base.model_copy(update=overrides) if overrides else base


# --------------------------------------------------------------------------
# 1a. Stage classification: free-form WhisperX progress strings → stage index
# --------------------------------------------------------------------------


def test_finalize_stages_ladder_matches_pipeline_order() -> None:
    assert FINALIZE_STAGES == ("load", "transcribe", "align", "diarize", "persist")


@pytest.mark.parametrize(
    ("message", "expected_stage"),
    [
        # Real messages emitted by offline/whisperx_pipeline.py::_progress_step.
        ("Loading full-session WAV into memory…", "load"),
        ("Loading Whisper model 'small' on 'cpu' (compute='int8')…", "load"),
        ("Transcribing (this can take several minutes)…", "transcribe"),
        ("Transcribe done (42 raw segment(s)); unloading model…", "transcribe"),
        ("Loading alignment model for language='en' on 'cpu'…", "align"),
        ("Aligning word timestamps…", "align"),
        ("Alignment finished.", "align"),
        ("Loading diarization model on 'cpu' (HF token required)…", "diarize"),
        ("Running speaker diarization…", "diarize"),
        ("Assigning speakers to words…", "diarize"),
        # Compute is over → what remains is the persist step. "WhisperX pass
        # complete" is the pipeline's LAST callback, emitted after these on both
        # the token and no-token paths — it must not read as an earlier stage.
        ("Diarization finished.", "persist"),
        ("Skipping diarization (no HF_TOKEN).", "persist"),
        ("WhisperX pass complete (128 segment(s)).", "persist"),
    ],
)
def test_stage_index_classifies_real_pipeline_messages(message: str, expected_stage: str) -> None:
    assert FINALIZE_STAGES[select_finalize_stage_index(message)] == expected_stage


def test_stage_index_unknown_or_missing_message_maps_to_load() -> None:
    # "starting…" (reducer's initial stage) and anything unrecognized must not crash
    # the deck — they read as the earliest stage.
    assert select_finalize_stage_index(None) == 0
    assert select_finalize_stage_index("starting…") == 0
    assert select_finalize_stage_index("???") == 0


# Every progress string run_whisperx_finalize emits, in true emission order
# (grep `_progress_step` in offline/whisperx_pipeline.py). Two real paths:
# HF token + alignment, and the no-token fallback.
_FULL_RUN_HF = (
    "Loading full-session WAV into memory…",
    "Loading Whisper model 'small' on 'cpu' (compute='int8')…",
    "Transcribing (this can take several minutes)…",
    "Transcribe done (42 raw segment(s)); unloading model…",
    "Loading alignment model for language='en' on 'cpu'…",
    "Aligning word timestamps…",
    "Alignment finished.",
    "Loading diarization model on 'cpu' (HF token required)…",
    "Running speaker diarization…",
    "Assigning speakers to words…",
    "Diarization finished.",
    "WhisperX pass complete (42 segment(s)).",
)
_FULL_RUN_NO_TOKEN = (
    "Loading full-session WAV into memory…",
    "Loading Whisper model 'small' on 'cpu' (compute='int8')…",
    "Transcribing (this can take several minutes)…",
    "Transcribe done (42 raw segment(s)); unloading model…",
    "Loading alignment model for language='en' on 'cpu'…",
    "Aligning word timestamps…",
    "Alignment finished.",
    "Skipping diarization (no HF_TOKEN).",
    "WhisperX pass complete (42 segment(s)).",
)


@pytest.mark.parametrize("run", [_FULL_RUN_HF, _FULL_RUN_NO_TOKEN], ids=["hf-token", "no-token"])
def test_stage_index_is_monotonic_over_a_true_full_run(run: tuple[str, ...]) -> None:
    indices = [select_finalize_stage_index(m) for m in run]
    assert indices == sorted(indices), list(zip(run, indices, strict=True))
    assert indices[0] == 0
    assert indices[-1] == len(FINALIZE_STAGES) - 1


@pytest.mark.parametrize("run", [_FULL_RUN_HF, _FULL_RUN_NO_TOKEN], ids=["hf-token", "no-token"])
def test_reducer_stage_index_never_moves_backwards_over_a_true_full_run(
    run: tuple[str, ...],
) -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_NOW),
    )
    seen: list[int] = [state.finalize_stage_index]
    for message in run:
        state = reduce(
            state, act.FinalizeProgressUpdated(session_id=sid, stage=message, at=_NOW)
        )
        seen.append(state.finalize_stage_index)
    assert seen == sorted(seen), list(zip(("<start>", *run), seen, strict=True))
    assert seen[-1] == len(FINALIZE_STAGES) - 1


def test_reducer_stage_index_holds_high_water_mark_on_unknown_wording() -> None:
    # Future pipeline wording drift must degrade to "bar holds", never "bar resets".
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_NOW),
    )
    state = reduce(
        state,
        act.FinalizeProgressUpdated(session_id=sid, stage="Running speaker diarization…", at=_NOW),
    )
    assert state.finalize_stage_index == 3
    state = reduce(
        state, act.FinalizeProgressUpdated(session_id=sid, stage="Wrapping up…", at=_NOW)
    )
    assert state.finalize_stage_index == 3, "unrecognized message must not run the bar backwards"


def test_reducer_new_job_resets_stage_index() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="A", at=_NOW),
    )
    state = reduce(
        state,
        act.FinalizeProgressUpdated(session_id=sid, stage="Diarization finished.", at=_NOW),
    )
    state = reduce(
        state,
        act.FinalizeSessionSucceeded(
            session_id=sid, segment_count=1, live_lines=None, at=_NOW, speakers_labelled=True
        ),
    )
    state = reduce(state, act.FinalizeSessionStarted(session_id=uuid4(), title="B", at=_NOW))
    assert state.finalize_stage_index == 0, "the next job must start with a fresh bar"


# --------------------------------------------------------------------------
# 1b. Stage bar rendering (text bar — fits the deck's Static line)
# --------------------------------------------------------------------------


def test_stage_bar_fills_one_cell_per_stage() -> None:
    total = len(FINALIZE_STAGES)
    for idx in range(total):
        plain = _plain(stage_bar_markup(idx, total))
        assert len(plain) == total, "bar keeps a fixed footprint"
        assert plain == "▰" * (idx + 1) + "▱" * (total - idx - 1)


def test_stage_bar_clamps_out_of_range_index() -> None:
    total = len(FINALIZE_STAGES)
    assert _plain(stage_bar_markup(-3, total)) == "▰" + "▱" * (total - 1)
    assert _plain(stage_bar_markup(99, total)) == "▰" * total


def test_deck_running_job_shows_stage_bar_advancing() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_NOW),
    )
    early = finalize_deck_markup(state)
    assert early is not None
    assert "▰▱▱▱▱" in _plain(early), "job start renders the load stage"

    state = reduce(
        state,
        act.FinalizeProgressUpdated(session_id=sid, stage="Running speaker diarization…", at=_NOW),
    )
    late = finalize_deck_markup(state)
    assert late is not None
    assert "▰▰▰▰▱" in _plain(late), "diarize stage fills four of five cells"
    # B7 contract intact: title + raw stage text still visible alongside the bar.
    assert "Speaker ID" in _plain(late)
    assert "Running speaker diarization…" in _plain(late)


def test_deck_persisted_outcome_has_no_stage_bar() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_NOW),
    )
    state = reduce(
        state,
        act.FinalizeSessionSucceeded(
            session_id=sid, segment_count=9, live_lines=None, at=_NOW, speakers_labelled=True
        ),
    )
    markup = finalize_deck_markup(state)
    assert markup is not None
    assert "▰" not in _plain(markup), "finished job shows the outcome, not a stuck bar"


def test_deck_bar_stays_full_through_the_terminal_pass_complete_message() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_NOW),
    )
    for message in _FULL_RUN_HF:
        state = reduce(
            state, act.FinalizeProgressUpdated(session_id=sid, stage=message, at=_NOW)
        )
        markup = finalize_deck_markup(state)
        assert markup is not None
    # The last two messages ("Diarization finished.", "WhisperX pass complete…")
    # both render a full bar — the persist window must not collapse to load.
    assert "▰▰▰▰▰" in _plain(markup)


def test_deck_truncates_long_stage_text_so_queued_count_survives() -> None:
    sid = uuid4()
    state = initial_app_state()
    state = reduce(state, act.FinalizeSessionQueued(session_id=sid, title="A", at=_NOW))
    state = reduce(state, act.FinalizeSessionStarted(session_id=sid, title="A", at=_NOW))
    state = reduce(state, act.FinalizeSessionQueued(session_id=uuid4(), title="B", at=_NOW))
    long_stage = "Loading Whisper model 'large-v3-turbo' on 'cpu' (compute='int8')…"
    state = reduce(
        state, act.FinalizeProgressUpdated(session_id=sid, stage=long_stage, at=_NOW)
    )
    markup = finalize_deck_markup(state)
    assert markup is not None
    plain = _plain(markup)
    assert "1 queued" in plain
    assert long_stage not in plain, "raw stage text must be truncated in the deck"
    assert "Loading Whisper model" in plain, "truncation keeps the informative prefix"


# --------------------------------------------------------------------------
# 2. Per-chunk transcription progress (reducer + bridge + selector)
# --------------------------------------------------------------------------


def test_reducer_chunk_processing_started_and_finished() -> None:
    s0 = _recording_state()
    s1 = reduce(s0, act.ChunkProcessingStarted(at=_NOW))
    assert s1.chunk_processing is True
    assert s1.chunks_processed == 0
    s2 = reduce(s1, act.ChunkProcessingFinished(at=_NOW))
    assert s2.chunk_processing is False
    assert s2.chunks_processed == 1


def test_reducer_recording_start_resets_chunk_progress() -> None:
    dirty = _recording_state(chunk_processing=True, chunks_processed=7)
    s = reduce(
        dirty,
        act.RecordingStarted(
            session_id=uuid4(),
            title="t",
            audio_source="mon",
            microphone_source=None,
            chunk_seconds=10,
            at=_NOW,
        ),
    )
    assert s.chunk_processing is False
    assert s.chunks_processed == 0


def test_reducer_recording_stop_clears_processing_flag() -> None:
    s = reduce(
        _recording_state(chunk_processing=True, chunks_processed=3),
        act.RecordingStopped(at=_NOW),
    )
    assert s.chunk_processing is False


def test_bridge_maps_chunk_lifecycle_events() -> None:
    sid, cid = uuid4(), uuid4()
    started = application_events_to_actions(
        ev.TranscriptionChunkStarted(session_id=sid, chunk_id=cid, at=_NOW)
    )
    assert any(isinstance(a, act.ChunkProcessingStarted) for a in started)

    done_events: tuple[ev.ApplicationEvent, ...] = (
        ev.TranscriptionChunkCompleted(session_id=sid, chunk_id=cid, at=_NOW),
        ev.TranscriptionChunkEmpty(session_id=sid, chunk_id=cid, at=_NOW),
        ev.TranscriptionChunkFailed(session_id=sid, chunk_id=cid, message="x", at=_NOW),
        # A silent-skipped chunk still *happened* — the counter must not freeze
        # during silence (F1 silence-skip would otherwise look like a stall).
        ev.AudioChunkSkippedSilent(session_id=sid, chunk_id=cid, rms_dbfs=-60.0, at=_NOW),
    )
    for done_event in done_events:
        actions = application_events_to_actions(done_event)
        assert any(isinstance(a, act.ChunkProcessingFinished) for a in actions), done_event


def test_chunk_progress_label_states() -> None:
    assert select_chunk_progress_label(initial_app_state()) is None  # idle → nothing
    assert select_chunk_progress_label(_recording_state()) is None  # nothing happened yet
    processing = _recording_state(chunk_processing=True, chunks_processed=2)
    assert select_chunk_progress_label(processing) == "#3 transcribing…"
    done = _recording_state(chunk_processing=False, chunks_processed=2)
    assert select_chunk_progress_label(done) == "#2 done"


# --------------------------------------------------------------------------
# 3. Next-chunk countdown (pure selector; the existing 1s tick re-renders it)
# --------------------------------------------------------------------------


def test_next_chunk_eta_counts_down_from_last_chunk_anchor() -> None:
    state = _recording_state(last_level_at=_NOW)
    assert select_next_chunk_eta_seconds(state, _NOW + timedelta(seconds=3)) == 7
    assert select_next_chunk_eta_seconds(state, _NOW + timedelta(seconds=9.5)) == 1


def test_next_chunk_eta_clamps_to_zero_when_overdue() -> None:
    state = _recording_state(last_level_at=_NOW)
    assert select_next_chunk_eta_seconds(state, _NOW + timedelta(seconds=25)) == 0


def test_next_chunk_eta_uses_recording_start_before_first_chunk() -> None:
    state = _recording_state()  # no last_level_at yet
    assert select_next_chunk_eta_seconds(state, _NOW + timedelta(seconds=4)) == 6


def test_next_chunk_eta_none_when_not_recording() -> None:
    assert select_next_chunk_eta_seconds(initial_app_state(), _NOW) is None


# --------------------------------------------------------------------------
# 4. Live-tab Audio card: progress + countdown live on the existing Chunk line
# --------------------------------------------------------------------------


def _chunk_line(state: AppState, now: datetime) -> str:
    return next(line for line in build_audio_card_lines(state, now) if "Chunk" in line)


def test_audio_card_chunk_line_idle_keeps_plain_chunk_length() -> None:
    line = _plain(_chunk_line(initial_app_state(), _NOW))
    assert "10s" in line
    assert "next" not in line
    assert "transcribing" not in line


def test_audio_card_chunk_line_shows_progress_and_countdown_while_recording() -> None:
    state = _recording_state(chunk_processing=True, chunks_processed=1, last_level_at=_NOW)
    line = _plain(_chunk_line(state, _NOW + timedelta(seconds=6)))
    assert "#2 transcribing…" in line
    assert "next 4s" in line


def test_audio_card_chunk_line_fits_the_sidebar_without_wrapping() -> None:
    # U8 density: the sidebar is 46 cells wide (~42 usable) — even a long-running
    # meeting's worst-case line must not wrap the card taller.
    state = _recording_state(chunk_processing=True, chunks_processed=998, last_level_at=_NOW)
    line = _plain(_chunk_line(state, _NOW))
    assert len(line) <= 42, line


# --------------------------------------------------------------------------
# 5. Pilot: the stage bar reaches the real deck widget (no direct mutation)
# --------------------------------------------------------------------------


async def test_deck_widget_renders_stage_bar_during_finalize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from textual.widgets import Static

    session = MeetingSession(id=uuid4(), title="Ops review")
    container = make_mock_tui_container(tmp_path, [session])
    app, store, controller = make_tui_harness(container)

    release = asyncio.Event()

    async def fake_finalize_offline(*, progress: object = None, **kwargs: object) -> int:
        assert callable(progress)
        progress("Running speaker diarization…")
        await release.wait()
        return 4

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=session.id, at=datetime.now(UTC))
        )
        await pilot.pause()
        deck = str(app.query_one("#deck-main", Static).render())
        assert "▰▰▰▰▱" in deck, "diarize stage bar must be visible in the deck"

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await pilot.pause()
        deck = str(app.query_one("#deck-main", Static).render())
        assert "▰" not in deck, "bar clears once the job is done"
