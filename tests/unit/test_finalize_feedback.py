"""B7 — in-TUI Speaker ID / finalize must give visible feedback while it runs.

Operator bug (2026-07-11): diarization was triggered from the UI for two
meetings; no progress and no errors were visible in-session, and the only
"completed"-ish feedback appeared at quit (structlog stdout lines flushed to
the restored terminal). Before this fix, start/progress lines went only to the
hidden Logs tab and the completion notice rendered only into the Live-tab
``#notices`` Static — invisible from the Meetings tab where Speaker ID is
actually triggered.

These tests pin the visible-feedback contract:

- queue / start / progress / success / failure are all reflected in ``AppState``;
- the always-visible status deck renders the active job + stage while running,
  and the last result *persists* there after completion (not just a 3s toast);
- success is honest when diarization labelled nobody (B4 parity: "set HF_TOKEN");
- failure surfaces as a persistent error that points at the Logs tab;
- re-triggering an already-queued job tells the user instead of silently no-oping.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.reducer import reduce
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.rendering import build_deck_markup

from tests.unit.conftest import (
    build_sqlite_container,
    make_mock_tui_container,
    make_tui_harness,
    spy_dispatch,
    sqlite_test_settings,
)


def _t() -> datetime:
    return datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Reducer: finalize job lifecycle is visible in AppState
# --------------------------------------------------------------------------


def test_reducer_finalize_queued_then_started_tracks_active_job() -> None:
    sid = uuid4()
    s0 = initial_app_state()
    s1 = reduce(s0, act.FinalizeSessionQueued(session_id=sid, title="Standup", at=_t()))
    assert s1.finalize_queued_count == 1
    assert any("Standup" in line for line in s1.ui_log_lines)

    s2 = reduce(s1, act.FinalizeSessionStarted(session_id=sid, title="Standup", at=_t()))
    assert s2.finalize_active_session_id == sid
    assert s2.finalize_active_title == "Standup"
    assert s2.finalize_queued_count == 0
    assert s2.finalize_stage  # some initial stage text
    assert s2.finalize_last_result is None  # a new job clears the previous result


def test_reducer_finalize_progress_updates_stage_and_logs() -> None:
    sid = uuid4()
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Standup", at=_t()),
    )
    s1 = reduce(
        s0,
        act.FinalizeProgressUpdated(session_id=sid, stage="Transcribing…", at=_t()),
    )
    assert s1.finalize_stage == "Transcribing…"
    assert any("Transcribing…" in line for line in s1.ui_log_lines)


def test_reducer_finalize_succeeded_persists_result_and_clears_active() -> None:
    sid = uuid4()
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Standup", at=_t()),
    )
    s1 = reduce(
        s0,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=42,
            live_lines=None,
            at=_t(),
            speakers_labelled=True,
        ),
    )
    assert s1.finalize_active_session_id is None
    assert s1.finalize_stage is None
    assert s1.finalize_last_result is not None
    assert "42 segment" in s1.finalize_last_result
    assert "Standup" in s1.finalize_last_result
    assert s1.finalize_last_result_level == "info"
    # The existing notices contract stays intact.
    assert "42 segment" in s1.notices[-1]


def test_reducer_finalize_succeeded_unlabelled_is_honest_about_hf_token() -> None:
    # B4 parity: WhisperX ran but diarization labelled nobody — say so, loudly.
    sid = uuid4()
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Standup", at=_t()),
    )
    s1 = reduce(
        s0,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=7,
            live_lines=None,
            at=_t(),
            speakers_labelled=False,
        ),
    )
    assert s1.finalize_last_result is not None
    assert "NOT labelled" in s1.finalize_last_result
    assert "HF_TOKEN" in s1.finalize_last_result
    assert s1.finalize_last_result_level == "warning"


def test_reducer_finalize_failed_is_persistent_error_and_clears_active() -> None:
    sid = uuid4()
    s0 = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Standup", at=_t()),
    )
    s1 = reduce(
        s0,
        act.FinalizeSessionFailed(session_id=sid, message="Finalize failed: boom", at=_t()),
    )
    assert s1.finalize_active_session_id is None
    assert s1.finalize_last_result == "Finalize failed: boom"
    assert s1.finalize_last_result_level == "error"
    # Persists in the errors panel and the Logs tab, like ErrorRaised.
    assert any("boom" in e.message for e in s1.recent_errors)
    assert any("boom" in line for line in s1.ui_log_lines)


# --------------------------------------------------------------------------
# Status deck: the always-visible chrome shows the job on every tab
# --------------------------------------------------------------------------


def test_deck_shows_active_finalize_job_with_stage() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_t()),
    )
    state = reduce(
        state,
        act.FinalizeProgressUpdated(session_id=sid, stage="Transcribing…", at=_t()),
    )
    markup = build_deck_markup(state, _t())
    assert "Speaker ID" in markup
    assert "Transcribing…" in markup


def test_deck_shows_queued_count_behind_active_job() -> None:
    sid = uuid4()
    state = initial_app_state()
    state = reduce(state, act.FinalizeSessionQueued(session_id=sid, title="A", at=_t()))
    state = reduce(state, act.FinalizeSessionStarted(session_id=sid, title="A", at=_t()))
    state = reduce(state, act.FinalizeSessionQueued(session_id=uuid4(), title="B", at=_t()))
    markup = build_deck_markup(state, _t())
    assert "1 queued" in markup


def test_deck_persists_last_result_after_completion() -> None:
    sid = uuid4()
    state = reduce(
        initial_app_state(),
        act.FinalizeSessionStarted(session_id=sid, title="Weekly sync", at=_t()),
    )
    state = reduce(
        state,
        act.FinalizeSessionSucceeded(
            session_id=sid,
            segment_count=9,
            live_lines=None,
            at=_t(),
            speakers_labelled=True,
        ),
    )
    markup = build_deck_markup(state, _t())
    assert "9 segment" in markup  # completion stays visible, not a transient toast


def test_deck_is_quiet_when_no_finalize_activity() -> None:
    markup = build_deck_markup(initial_app_state(), _t())
    assert "Speaker ID" not in markup


# --------------------------------------------------------------------------
# Controller: the effect layer emits the lifecycle actions
# --------------------------------------------------------------------------


def _seed_session(container: Container, *, title: str, speaker: str) -> UUID:
    session = MeetingSession(title=title)
    container.sessions.create(session)
    container.transcripts.append(
        TranscriptSegment(
            session_id=session.id,
            started_at=session.started_at,
            ended_at=session.started_at + timedelta(seconds=1),
            text="hello",
            speaker=speaker,
        )
    )
    return session.id


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_controller_emits_queued_started_progress_succeeded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, title="Team weekly", speaker="unknown")
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(*, progress: object = None, **kwargs: object) -> int:
        assert callable(progress), "TUI must wire the progress callback"
        progress("Transcribing…")
        await asyncio.sleep(0)
        return 5

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(
            store, act.FinalizeSessionRequested(session_id=sid, at=datetime.now(UTC))
        )
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await asyncio.sleep(0.05)  # let call_soon_threadsafe progress emits land
    finally:
        await _cancel(controller._finalize_worker_task)

    queued = [a for a in dispatched if isinstance(a, act.FinalizeSessionQueued)]
    started = [a for a in dispatched if isinstance(a, act.FinalizeSessionStarted)]
    progressed = [a for a in dispatched if isinstance(a, act.FinalizeProgressUpdated)]
    succeeded = [a for a in dispatched if isinstance(a, act.FinalizeSessionSucceeded)]
    assert [a.title for a in queued] == ["Team weekly"]
    assert [a.title for a in started] == ["Team weekly"]
    assert any(a.stage == "Transcribing…" for a in progressed)
    assert len(succeeded) == 1
    # Seeded transcript is still all-"unknown" → success must carry the honesty flag.
    assert succeeded[0].speakers_labelled is False


@pytest.mark.asyncio
async def test_controller_success_reports_labelled_speakers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, title="Labelled", speaker="unknown")
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        container.transcripts.append(
            TranscriptSegment(
                session_id=session_id,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC) + timedelta(seconds=1),
                text="labelled",
                speaker="SPEAKER_00",
            )
        )
        return 2

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(
            store, act.FinalizeSessionRequested(session_id=sid, at=datetime.now(UTC))
        )
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
    finally:
        await _cancel(controller._finalize_worker_task)

    succeeded = [a for a in dispatched if isinstance(a, act.FinalizeSessionSucceeded)]
    assert len(succeeded) == 1
    assert succeeded[0].speakers_labelled is True


@pytest.mark.asyncio
async def test_controller_failure_emits_finalize_failed_pointing_at_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, title="Broken", speaker="unknown")
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(**kwargs: object) -> int:
        raise RuntimeError("bad value(s) in fds_to_keep")

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(
            store, act.FinalizeSessionRequested(session_id=sid, at=datetime.now(UTC))
        )
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
    finally:
        await _cancel(controller._finalize_worker_task)

    failed = [a for a in dispatched if isinstance(a, act.FinalizeSessionFailed)]
    assert len(failed) == 1
    assert "fds_to_keep" in failed[0].message
    assert "Logs" in failed[0].message  # points the user at the Logs tab / log file


@pytest.mark.asyncio
async def test_controller_duplicate_enqueue_tells_the_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pressing Speaker ID for a meeting that is already queued/running was a
    # silent no-op — exactly what the operator hit when startup recovery had
    # already queued the same session. It must say so now.
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, title="Dup", speaker="unknown")
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    release = asyncio.Event()

    async def fake_finalize_offline(**kwargs: object) -> int:
        await release.wait()
        return 1

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        controller._enqueue_finalize(sid)
        dispatched = spy_dispatch(store)
        controller._enqueue_finalize(sid)  # duplicate while queued/running
        assert any(
            isinstance(a, act.NoticeRaised) and "already" in a.message.lower() for a in dispatched
        )
    finally:
        release.set()
        await _cancel(controller._finalize_worker_task)


# --------------------------------------------------------------------------
# Live app (Pilot): feedback is visible without quitting
# --------------------------------------------------------------------------


async def test_deck_widget_shows_finalize_progress_and_completion_without_quit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from textual.widgets import Static

    session = MeetingSession(id=uuid4(), title="Ops review")
    container = make_mock_tui_container(tmp_path, [session])
    app, store, controller = make_tui_harness(container)

    release = asyncio.Event()

    async def fake_finalize_offline(*, progress: object = None, **kwargs: object) -> int:
        assert callable(progress)
        progress("Transcribing…")
        await release.wait()
        return 11

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
        assert "Speaker ID" in deck, "running job must be visible in the always-on deck"
        assert "Transcribing…" in deck

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await pilot.pause()
        deck = str(app.query_one("#deck-main", Static).render())
        assert "11 segment" in deck, "completion must persist in the deck, in-session"
        assert store.get_state().notices, "completion must also land in notices"
