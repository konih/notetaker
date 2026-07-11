"""F10 — persistent finalize/Speaker-ID jobs panel + discoverable Retranscribe.

Operator request (2026-07-11): starting Speaker ID only raises a short toast —
"I would also like visual feedback about the progress and running jobs. I would
also like the option to retranscribe."

B7 already surfaces the *single* active job in the status deck and F8 draws its
stage bar; what is still missing (and pinned here) is:

- a per-job **jobs list** in ``AppState`` (queued / running / done / failed, with
  timestamps, the latest F8 stage, and a why-failed reason per B4/B3 honesty),
  bounded so it cannot grow without limit;
- a pure ``build_finalize_jobs_lines`` selector rendering that list, and a
  persistent panel on the Meetings tab (where Speaker ID is triggered) that is
  invisible when there has been no job activity;
- the quit-time backlog drop (B7's known wart) clearing the queued rows and the
  deck's "+N queued" counter instead of leaving them stale;
- an explicitly *discoverable* Retranscribe affordance: "Speaker ID" already
  re-runs the full WhisperX transcription on any session, so the canonical
  action is relabelled "Speaker ID / Retranscribe" (one action, one key — no
  second pipeline), with the toolbar button carrying a tooltip and the start
  notice saying that the transcript is replaced.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    AppState,
    FinalizeJobStatus,
    initial_app_state,
)
from live_meeting_transcriber.ui.state.reducer import reduce
from live_meeting_transcriber.ui.state.selectors import build_finalize_jobs_lines
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp
from live_meeting_transcriber.ui.tui.footer_bindings import FOOTER_ACTIONS
from live_meeting_transcriber.ui.tui.help_overlay import (
    build_help_sections,
    format_help_markup,
)
from live_meeting_transcriber.ui.tui.meeting_browser import MeetingBrowser
from live_meeting_transcriber.ui.tui.meeting_toolbar import MEETING_TOOLBAR_ACTIONS

from tests.unit.conftest import make_mock_tui_container, make_tui_harness

_FINALIZE_PATCH = "live_meeting_transcriber.application.finalize_service.finalize_session_offline"

_T0 = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _t(seconds: int = 0) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _plain(markup: str) -> str:
    """Strip console markup tags so lines can be matched as plain text."""
    return re.sub(r"\[/?[^\[\]]*\]", "", markup)


def _queued(state: AppState, sid: UUID, title: str, at: datetime | None = None) -> AppState:
    return reduce(state, act.FinalizeSessionQueued(session_id=sid, title=title, at=at or _t()))


def _started(state: AppState, sid: UUID, title: str, at: datetime | None = None) -> AppState:
    return reduce(state, act.FinalizeSessionStarted(session_id=sid, title=title, at=at or _t()))


def _succeeded(state: AppState, sid: UUID, at: datetime | None = None) -> AppState:
    return reduce(
        state,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=42,
            live_lines=None,
            at=at or _t(),
            speakers_labelled=True,
        ),
    )


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# --------------------------------------------------------------------------
# Reducer: the jobs list tracks the full lifecycle in AppState
# --------------------------------------------------------------------------


def test_queued_job_appears_in_jobs_list() -> None:
    sid = uuid4()
    s = _queued(initial_app_state(), sid, "Standup")
    assert len(s.finalize_jobs) == 1
    job = s.finalize_jobs[0]
    assert job.session_id == str(sid)
    assert job.title == "Standup"
    assert job.status == FinalizeJobStatus.queued
    assert job.enqueued_at == _t()
    assert job.started_at is None
    assert job.finished_at is None


def test_started_promotes_queued_job_to_running() -> None:
    sid = uuid4()
    s = _queued(initial_app_state(), sid, "Standup", at=_t(0))
    s = _started(s, sid, "Standup", at=_t(5))
    assert len(s.finalize_jobs) == 1
    job = s.finalize_jobs[0]
    assert job.status == FinalizeJobStatus.running
    assert job.enqueued_at == _t(0)
    assert job.started_at == _t(5)


def test_progress_updates_running_job_stage_with_high_water_index() -> None:
    sid = uuid4()
    s = _started(_queued(initial_app_state(), sid, "Standup"), sid, "Standup")
    s = reduce(s, act.FinalizeProgressUpdated(session_id=sid, stage="Transcribing…", at=_t(10)))
    job = s.finalize_jobs[0]
    assert job.stage == "Transcribing…"
    assert job.stage_index == 1
    # A late unrecognized message must not run the per-job bar backwards (F8 parity).
    s = reduce(s, act.FinalizeProgressUpdated(session_id=sid, stage="Diarizing…", at=_t(20)))
    s = reduce(s, act.FinalizeProgressUpdated(session_id=sid, stage="something odd", at=_t(30)))
    job = s.finalize_jobs[0]
    assert job.stage == "something odd"
    assert job.stage_index == 3


def test_succeeded_marks_job_done_with_detail() -> None:
    sid = uuid4()
    s = _started(_queued(initial_app_state(), sid, "Standup", at=_t(0)), sid, "Standup", at=_t(5))
    s = _succeeded(s, sid, at=_t(65))
    job = s.finalize_jobs[0]
    assert job.status == FinalizeJobStatus.done
    assert job.finished_at == _t(65)
    assert job.detail is not None and "42 segment" in job.detail
    assert job.level == "info"


def test_succeeded_unlabelled_keeps_hf_token_honesty_in_job_detail() -> None:
    sid = uuid4()
    s = _started(_queued(initial_app_state(), sid, "Standup"), sid, "Standup")
    s = reduce(
        s,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=7,
            live_lines=None,
            at=_t(60),
            speakers_labelled=False,
        ),
    )
    job = s.finalize_jobs[0]
    assert job.status == FinalizeJobStatus.done
    assert job.detail is not None and "HF_TOKEN" in job.detail
    assert job.level == "warning"


def test_failed_marks_job_failed_with_reason() -> None:
    sid = uuid4()
    s = _started(_queued(initial_app_state(), sid, "Broken"), sid, "Broken")
    s = reduce(
        s,
        act.FinalizeSessionFailed(
            session_id=sid,
            message="Speaker ID / finalize skipped: install whisperx extra.",
            at=_t(30),
        ),
    )
    job = s.finalize_jobs[0]
    assert job.status == FinalizeJobStatus.failed
    assert job.detail is not None and "whisperx extra" in job.detail  # why, not a silent drop (B4)
    assert job.level == "error"
    assert job.finished_at == _t(30)


def test_second_enqueue_while_running_shows_queued_row() -> None:
    a, b = uuid4(), uuid4()
    s = _queued(initial_app_state(), a, "First")
    s = _started(s, a, "First")
    s = _queued(s, b, "Second")
    statuses = {j.title: j.status for j in s.finalize_jobs}
    assert statuses == {
        "First": FinalizeJobStatus.running,
        "Second": FinalizeJobStatus.queued,
    }
    # …and the queued row promotes to running when the worker picks it up (B2 queue).
    s = _succeeded(s, a)
    s = _started(s, b, "Second")
    statuses = {j.title: j.status for j in s.finalize_jobs}
    assert statuses["Second"] == FinalizeJobStatus.running


def test_finished_jobs_retained_capped_to_last_five() -> None:
    # Retention decision: finished (done/failed) rows are working memory for
    # "what happened while I was away", not an archive — notices/errors/Logs and
    # the DB itself are the durable record. Five keeps the card within the
    # Meetings list-pane height budget.
    s = initial_app_state()
    sids = [uuid4() for _ in range(7)]
    for i, sid in enumerate(sids):
        s = _queued(s, sid, f"Meeting {i}", at=_t(i * 100))
        s = _started(s, sid, f"Meeting {i}", at=_t(i * 100 + 1))
        s = _succeeded(s, sid, at=_t(i * 100 + 50))
    assert len(s.finalize_jobs) == 5
    kept_titles = [j.title for j in s.finalize_jobs]
    assert "Meeting 0" not in kept_titles and "Meeting 1" not in kept_titles
    assert "Meeting 6" in kept_titles


def test_requeue_replaces_previous_outcome_for_same_session() -> None:
    sid = uuid4()
    s = _succeeded(_started(_queued(initial_app_state(), sid, "Redo"), sid, "Redo"), sid)
    assert s.finalize_jobs[0].status == FinalizeJobStatus.done
    s = _queued(s, sid, "Redo", at=_t(200))
    same_session = [j for j in s.finalize_jobs if j.session_id == str(sid)]
    assert len(same_session) == 1, "a re-run must replace the session's old outcome row"
    assert same_session[0].status == FinalizeJobStatus.queued


def test_backlog_drop_removes_queued_jobs_and_clears_queued_count() -> None:
    # B7's known wart: quit-time backlog drop left the deck showing a stale
    # "+N queued" and would have left stale queued rows in the panel.
    a, b, c = uuid4(), uuid4(), uuid4()
    s = _queued(initial_app_state(), a, "Running one")
    s = _started(s, a, "Running one")
    s = _queued(s, b, "Dropped one")
    s = _queued(s, c, "Dropped two")
    assert s.finalize_queued_count == 2
    s = reduce(s, act.FinalizeQueueBacklogDropped(session_ids=(b, c), at=_t(400)))
    assert s.finalize_queued_count == 0
    statuses = {j.title: j.status for j in s.finalize_jobs}
    assert "Dropped one" not in statuses and "Dropped two" not in statuses
    assert statuses["Running one"] == FinalizeJobStatus.running


# --------------------------------------------------------------------------
# Pure selector: build_finalize_jobs_lines renders the panel rows
# --------------------------------------------------------------------------


def test_jobs_lines_empty_when_no_activity() -> None:
    assert build_finalize_jobs_lines(initial_app_state(), _t()) == []


def test_jobs_lines_running_row_shows_stage_bar_and_elapsed() -> None:
    sid = uuid4()
    s = _queued(initial_app_state(), sid, "Weekly sync", at=_t(0))
    s = _started(s, sid, "Weekly sync", at=_t(0))
    s = reduce(s, act.FinalizeProgressUpdated(session_id=sid, stage="Transcribing…", at=_t(10)))
    lines = build_finalize_jobs_lines(s, _t(90))
    assert len(lines) == 1
    line = lines[0]
    assert "Weekly sync" in _plain(line)
    assert "Transcribing…" in _plain(line)
    assert "▰" in line  # the F8 stage bar renders inside the job row
    assert "1:30" in _plain(line)  # elapsed since started_at


def test_jobs_lines_queued_row_says_queued() -> None:
    a, b = uuid4(), uuid4()
    s = _queued(initial_app_state(), a, "First", at=_t(0))
    s = _started(s, a, "First", at=_t(0))
    s = _queued(s, b, "Second", at=_t(5))
    lines = [_plain(line) for line in build_finalize_jobs_lines(s, _t(30))]
    assert len(lines) == 2
    assert "First" in lines[0]  # running row first
    assert "Second" in lines[1] and "queued" in lines[1]


def test_jobs_lines_failed_row_shows_reason() -> None:
    sid = uuid4()
    s = _started(_queued(initial_app_state(), sid, "Broken"), sid, "Broken")
    s = reduce(
        s,
        act.FinalizeSessionFailed(session_id=sid, message="set HF_TOKEN and re-run", at=_t(30)),
    )
    lines = [_plain(line) for line in build_finalize_jobs_lines(s, _t(60))]
    assert len(lines) == 1
    assert "Broken" in lines[0]
    assert "HF_TOKEN" in lines[0]  # why-failed, honest (B4)
    assert "✖" in lines[0]


def test_jobs_lines_done_row_shows_outcome() -> None:
    sid = uuid4()
    s = _succeeded(
        _started(_queued(initial_app_state(), sid, "Ops"), sid, "Ops", at=_t(0)), sid, at=_t(130)
    )
    lines = [_plain(line) for line in build_finalize_jobs_lines(s, _t(500))]
    assert len(lines) == 1
    assert "Ops" in lines[0]
    assert "✓" in lines[0]
    assert "42 segment" in lines[0]


def test_jobs_lines_fit_the_meetings_list_pane_width() -> None:
    # The panel lives in the 48-cell Meetings list pane (border + padding ≈ 44
    # usable): rows must not wrap, whatever the title/detail length.
    sid = uuid4()
    long_title = "A very long meeting title that would definitely overflow the pane"
    s = _started(_queued(initial_app_state(), sid, long_title), sid, long_title)
    s = reduce(
        s,
        act.FinalizeSessionFailed(session_id=sid, message="reason " * 30, at=_t(30)),
    )
    for line in build_finalize_jobs_lines(s, _t(60)):
        assert len(_plain(line)) <= 44, f"row wraps: {_plain(line)!r}"


# --------------------------------------------------------------------------
# Controller: quit-time backlog drop dispatches the cleanup action
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_finalize_idle_clears_queued_jobs_from_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from live_meeting_transcriber.config.settings import Settings

    session = MeetingSession(title="in flight")
    container = make_mock_tui_container(tmp_path, [session])
    store = Store()
    controller = TuiController(store=store, container=container, settings=Settings())

    release = asyncio.Event()

    async def fake_finalize_offline(**kwargs: object) -> int:
        await release.wait()
        return 1

    monkeypatch.setattr(_FINALIZE_PATCH, fake_finalize_offline)

    first, second = uuid4(), uuid4()
    controller._enqueue_finalize(first)
    controller._enqueue_finalize(second)
    await asyncio.sleep(0.05)  # first in flight, second queued
    assert store.get_state().finalize_queued_count == 1

    waiter = asyncio.create_task(controller.wait_finalize_idle())
    await asyncio.sleep(0.05)
    # The backlog is dropped immediately — no stale "+1 queued" during the wait.
    state = store.get_state()
    assert state.finalize_queued_count == 0
    assert all(j.status != FinalizeJobStatus.queued for j in state.finalize_jobs)

    release.set()
    try:
        await asyncio.wait_for(waiter, timeout=2.0)
    finally:
        await _cancel(controller._finalize_worker_task)


# --------------------------------------------------------------------------
# Live app (Pilot): the panel is a persistent Meetings-tab surface
# --------------------------------------------------------------------------


async def test_jobs_panel_hidden_when_idle(tmp_path: Path) -> None:
    from textual.widgets import Static, TabbedContent

    session = MeetingSession(id=uuid4(), title="Quiet")
    container = make_mock_tui_container(tmp_path, [session])
    app, _store, _controller = make_tui_harness(container)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        panel = app.query_one("#finalize-jobs-panel", Static)
        # ≤1 line idle budget: the panel costs zero rows before any job activity.
        assert panel.region.height <= 1, f"idle panel costs rows: {panel.region}"


async def test_jobs_panel_shows_running_then_queued_then_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from textual.widgets import Static, TabbedContent

    one = MeetingSession(id=uuid4(), title="Ops review")
    two = MeetingSession(id=uuid4(), title="Retro")
    container = make_mock_tui_container(tmp_path, [one, two])
    app, store, controller = make_tui_harness(container)

    release = asyncio.Event()

    async def fake_finalize_offline(*, progress: object = None, **kwargs: object) -> int:
        assert callable(progress)
        progress("Transcribing…")
        await release.wait()
        return 11

    monkeypatch.setattr(_FINALIZE_PATCH, fake_finalize_offline)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-meetings"
        await pilot.pause()
        # Drive two enqueues: one runs, one queues (exercises the B2 sequential queue).
        await store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=one.id, at=datetime.now(UTC))
        )
        await store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=two.id, at=datetime.now(UTC))
        )
        await pilot.pause()
        panel = app.query_one("#finalize-jobs-panel", Static)
        assert panel.display, "panel must be visible while jobs are active"
        rendered = _plain(str(panel.render()))
        assert "Ops review" in rendered
        assert "Transcribing…" in rendered
        assert "Retro" in rendered and "queued" in rendered

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await pilot.pause()
        rendered = _plain(str(panel.render()))
        assert "11 segment" in rendered, "done outcome must persist in the panel"
        await _cancel(controller._finalize_worker_task)


# --------------------------------------------------------------------------
# Retranscribe: one canonical action, discoverably named (OQ-F10-1/2 → (a)+(b))
# --------------------------------------------------------------------------


def test_canonical_action_is_labelled_speaker_id_slash_retranscribe() -> None:
    footer = next(a for a in FOOTER_ACTIONS if a.action == "finalize_speakers")
    assert footer.key == "ctrl+d"  # canonical key unchanged (U12; not terminal-aliased)
    assert "Retranscribe" in footer.label
    assert "Speaker ID" in footer.label


def test_meetings_binding_carries_the_same_retranscribe_label() -> None:
    finalize = [
        b
        for b in MeetingBrowser.BINDINGS
        if getattr(b, "action", "") == "finalize_selected_speakers"
    ]
    assert finalize, "Meetings tab must bind the Speaker ID / Retranscribe action"
    footer = next(a for a in FOOTER_ACTIONS if a.action == "finalize_speakers")
    for b in finalize:
        # Same key + same label in both regions (U12 shared-key rule).
        assert getattr(b, "key", "") == footer.key
        assert str(getattr(b, "description", "")) == footer.label


def test_help_overlay_lists_retranscribe() -> None:
    sections = build_help_sections(TranscriberApp.BINDINGS, MeetingBrowser.BINDINGS)
    markup = format_help_markup(sections)
    assert "Retranscribe" in markup


def test_toolbar_speaker_id_button_has_retranscribe_tooltip() -> None:
    # The width-budgeted button keeps its short label; the tooltip makes its
    # full-retranscribe behaviour visible (story: "relabel or add a tooltip").
    speaker_btn = next(
        a for a in MEETING_TOOLBAR_ACTIONS if a.button_id == "meeting-btn-speaker-id"
    )
    assert speaker_btn.tooltip is not None
    assert "retranscrib" in speaker_btn.tooltip.lower()
    assert "replace" in speaker_btn.tooltip.lower()  # says the transcript is replaced


def test_start_notice_says_retranscribe_replaces_transcript() -> None:
    from live_meeting_transcriber.ui.tui import meeting_actions

    notice = meeting_actions.SPEAKER_ID_STARTED_NOTICE
    assert "retranscrib" in notice.lower()
    assert "speaker" in notice.lower()
