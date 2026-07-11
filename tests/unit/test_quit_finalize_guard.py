"""B7 — quitting while a Speaker ID / finalize job runs must not discard results.

Confirmed against the operator's live DB and log (2026-07-11): two in-TUI
diarization runs each completed their WhisperX pass *during shutdown* — the
log shows "WhisperX pass complete (211 segment(s))" two seconds after the quit
keypress — yet the DB was never written (every segment still "unknown", app.db
mtime a day old). Root cause: ``action_quit`` called ``self.exit()`` outright;
the loop teardown cancelled the finalize worker task between the
``asyncio.to_thread`` WhisperX pass and ``_finalize_persist_segments``, while
``loop.shutdown_default_executor()`` still blocked on the worker thread — the
app hung for the remaining minutes of compute and then threw the result away.

Contract pinned here:

- ``TuiController.wait_finalize_idle()`` lets the in-flight job finish (and
  persist) while dropping queued-but-unstarted jobs (recoverable at startup);
- ``action_quit`` defers exit until the in-flight job has persisted, with a
  persistent user-visible notice;
- a second quit press force-quits immediately (escape hatch).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp

_FINALIZE_PATCH = "live_meeting_transcriber.application.finalize_service.finalize_session_offline"


def _mock_container(tmp_path: Path, session: MeetingSession) -> MagicMock:
    container = MagicMock()
    container.sessions.list.return_value = [session]
    container.sessions.get.return_value = session
    container.summaries.get_by_session.return_value = None
    container.transcripts.list_by_session.return_value = []
    container.session_speakers.get_map.return_value = {}
    container.settings.ensure_data_dir.return_value = tmp_path
    container.devices.list_sources.return_value = [object()]
    return container


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# --------------------------------------------------------------------------
# Controller: wait_finalize_idle drains safely
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_finalize_idle_finishes_inflight_and_drops_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = MeetingSession(title="in flight")
    container = _mock_container(tmp_path, session)
    store = Store()
    controller = TuiController(store=store, container=container, settings=Settings())

    release = asyncio.Event()
    completed: list[UUID] = []

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        await release.wait()
        completed.append(session_id)  # stands in for _finalize_persist_segments
        return 1

    monkeypatch.setattr(_FINALIZE_PATCH, fake_finalize_offline)

    first, second = uuid4(), uuid4()
    controller._enqueue_finalize(first)
    controller._enqueue_finalize(second)
    await asyncio.sleep(0.05)  # first job is now in flight, second still queued
    assert controller.finalize_busy

    waiter = asyncio.create_task(controller.wait_finalize_idle())
    await asyncio.sleep(0.05)
    assert not waiter.done()  # must wait for the in-flight job, not cancel it

    release.set()
    try:
        await asyncio.wait_for(waiter, timeout=2.0)
        # The in-flight job persisted; the queued-but-unstarted one was dropped
        # (startup recovery / finalize-pending picks it up next launch).
        assert completed == [first]
        assert not controller.finalize_busy
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_wait_finalize_idle_returns_immediately_when_idle(tmp_path: Path) -> None:
    session = MeetingSession(title="idle")
    container = _mock_container(tmp_path, session)
    controller = TuiController(store=Store(), container=container, settings=Settings())
    assert not controller.finalize_busy
    await asyncio.wait_for(controller.wait_finalize_idle(), timeout=1.0)


# --------------------------------------------------------------------------
# Live app (Pilot): quit defers until the job persisted; double-q forces
# --------------------------------------------------------------------------


def _make_app(container: MagicMock) -> tuple[TranscriberApp, Store, TuiController]:
    store = Store(state=initial_app_state())
    controller = TuiController(store=store, container=container, settings=Settings())
    store.register_effects(controller.handle)
    return (
        TranscriberApp(store=store, container=container, controller=controller),
        store,
        controller,
    )


async def test_quit_waits_for_inflight_finalize_to_persist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = MeetingSession(id=uuid4(), title="Long meeting")
    container = _mock_container(tmp_path, session)
    app, store, controller = _make_app(container)

    release = asyncio.Event()
    completed: list[UUID] = []

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        await release.wait()
        completed.append(session_id)
        return 3

    monkeypatch.setattr(_FINALIZE_PATCH, fake_finalize_offline)

    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda *a, **k: exits.append(True))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=session.id, at=datetime.now(UTC))
        )
        await pilot.pause()
        assert controller.finalize_busy

        await pilot.press("q")
        await pilot.pause()
        # The job hasn't finished: the app must NOT have exited yet…
        assert exits == [], "quit must not discard an in-flight Speaker ID job"
        assert not completed
        # …and the user must be told why, persistently (notice, not only a toast).
        state = store.get_state()
        assert any("speaker id" in n.lower() or "finalize" in n.lower() for n in state.notices)

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await pilot.pause()
        await pilot.pause()
        # Job persisted first, then the deferred quit fired.
        assert completed == [session.id]
        assert exits == [True]
        await _cancel(controller._finalize_worker_task)


async def test_second_quit_press_force_quits_immediately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = MeetingSession(id=uuid4(), title="Long meeting")
    container = _mock_container(tmp_path, session)
    app, store, controller = _make_app(container)

    release = asyncio.Event()

    async def fake_finalize_offline(**kwargs: object) -> int:
        await release.wait()
        return 1

    monkeypatch.setattr(_FINALIZE_PATCH, fake_finalize_offline)

    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda *a, **k: exits.append(True))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await store.dispatch_with_effects(
            act.FinalizeSessionRequested(session_id=session.id, at=datetime.now(UTC))
        )
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()
        assert exits == []  # deferred, job still running

        await pilot.press("q")
        await pilot.pause()
        assert exits == [True], "second quit press must force-quit"

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
        await _cancel(controller._finalize_worker_task)


async def test_quit_exits_promptly_when_no_finalize_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = MeetingSession(id=uuid4(), title="Quiet")
    container = _mock_container(tmp_path, session)
    app, _store, _controller = _make_app(container)

    exits: list[bool] = []
    monkeypatch.setattr(app, "exit", lambda *a, **k: exits.append(True))

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert exits == [True]
