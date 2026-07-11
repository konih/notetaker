"""Finalize (Speaker ID / diarization) must not block the TUI's message loop.

Root cause this guards against (confirmed against a real user database): the
old code awaited the whole multi-minute WhisperX pass directly inside
``TuiController.handle``, which is itself awaited from Textual's key-binding
dispatch — freezing the UI. Worse, auto-finalize-on-stop scheduled a bare
``asyncio.create_task`` with no reference held, so quitting shortly after
stopping a recording silently killed it before it finished; 0 of 31 real
sessions ever completed diarization as a result. The fix moves finalize onto
a tracked, sequential background queue and adds bounded startup recovery for
sessions that were dropped this way.
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
from live_meeting_transcriber.ui.state.store import Store

from tests.unit.conftest import build_sqlite_container, sqlite_test_settings


def _seed_ended_all_unknown_session(container: Container, *, ended_at: datetime) -> UUID:
    session = MeetingSession(title="dropped on exit")
    container.sessions.create(session)
    container._conn.execute(
        "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
        (ended_at.isoformat(), str(session.id)),
    )
    container._conn.commit()
    container.transcripts.append(
        TranscriptSegment(
            session_id=session.id,
            started_at=session.started_at,
            ended_at=session.started_at + timedelta(seconds=1),
            text="hello",
            speaker="unknown",
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
async def test_finalize_requested_runs_on_tracked_worker_not_inline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_ended_all_unknown_session(container, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    release = asyncio.Event()
    started = asyncio.Event()

    async def fake_finalize_offline(**kwargs: object) -> int:
        started.set()
        await release.wait()
        return 1

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        # handle() must return promptly — it must NOT block on the multi-minute pass.
        await asyncio.wait_for(
            controller.handle(
                store, act.FinalizeSessionRequested(session_id=sid, at=datetime.now(UTC))
            ),
            timeout=1.0,
        )
        # …yet the finalize actually runs, on a *tracked* background worker (not a bare
        # create_task that the event loop would GC / the app exit would kill).
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert controller._finalize_worker_task is not None
        assert not controller._finalize_worker_task.done()

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=1.0)
    finally:
        release.set()
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_enqueue_dedups_and_tracks_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    async def fake_finalize_offline(**kwargs: object) -> int:
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    sid = uuid4()
    # Two synchronous enqueues of the same session before the worker gets a turn:
    # the second is a no-op (deduped), so only one item is queued.
    controller._enqueue_finalize(sid)
    controller._enqueue_finalize(sid)
    assert controller._finalize_queue.qsize() == 1
    assert controller._finalize_worker_task is not None  # tracked, held on the controller

    try:
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=1.0)
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_auto_finalize_on_stop_enqueues_via_tracked_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The exact regression: stopping a recording with FINALIZE_ON_SESSION_STOP must go
    # through the tracked queue, never a bare create_task that a quick quit would kill.
    settings = sqlite_test_settings(tmp_path, FINALIZE_ON_SESSION_STOP=True)
    container = build_sqlite_container(settings)
    session = MeetingSession(title="live")
    container.sessions.create(session)
    sid = session.id
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)
    store.dispatch(
        act.RecordingStarted(
            session_id=sid,
            title="live",
            audio_source="default",
            microphone_source=None,
            chunk_seconds=10,
            at=datetime.now(UTC),
        )
    )

    enqueued: list[UUID] = []
    monkeypatch.setattr(controller, "_enqueue_finalize", enqueued.append)

    await controller.handle(store, act.RecordingStopRequested(at=datetime.now(UTC)))

    assert enqueued == [sid]


@pytest.mark.asyncio
async def test_startup_recovery_enqueues_recent_all_unknown_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN="fake-token")
    container = build_sqlite_container(settings)
    recent_sid = _seed_ended_all_unknown_session(
        container, ended_at=datetime.now(UTC) - timedelta(hours=1)
    )
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now(UTC)))
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=1.0)
        assert finalized == [recent_sid]
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_startup_recovery_skipped_without_hf_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN=None)
    container = build_sqlite_container(settings)
    _seed_ended_all_unknown_session(container, ended_at=datetime.now(UTC) - timedelta(hours=1))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now(UTC)))
        await asyncio.sleep(0.05)
        assert finalized == []
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_startup_recovery_skips_sessions_ended_outside_the_recovery_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = sqlite_test_settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN="fake-token")
    container = build_sqlite_container(settings)
    _seed_ended_all_unknown_session(container, ended_at=datetime.now(UTC) - timedelta(days=10))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id: UUID, **kwargs: object) -> int:
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now(UTC)))
        await asyncio.sleep(0.05)
        assert finalized == []
    finally:
        await _cancel(controller._finalize_worker_task)
