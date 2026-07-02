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
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.storage.repositories import (
    SqliteDiarizationRepository,
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.store import Store


def _settings(tmp_path, **overrides: object) -> Settings:
    db = tmp_path / "controller_test.sqlite3"
    return Settings(DATABASE_URL=f"sqlite:////{db}", **overrides)  # type: ignore[arg-type]


def _container(settings: Settings) -> Container:
    conn = open_connection(settings.database_url)
    return Container(
        settings=settings,
        _conn=conn,
        devices=None,  # type: ignore[arg-type]
        audio=None,  # type: ignore[arg-type]
        transcriber=None,  # type: ignore[arg-type]
        summarizer=None,  # type: ignore[arg-type]
        diarizer=None,  # type: ignore[arg-type]
        diarization_segments=SqliteDiarizationRepository(conn),
        sessions=SqliteMeetingSessionRepository(conn),
        transcripts=SqliteTranscriptRepository(conn),
        summaries=None,  # type: ignore[arg-type]
        people=None,  # type: ignore[arg-type]
        session_speakers=None,  # type: ignore[arg-type]
    )


def _seed_ended_all_unknown_session(container: Container, *, ended_at: datetime) -> UUID:
    session = MeetingSession(title="dropped on exit")
    container.sessions.create(session)
    container.sessions.conn.execute(
        "UPDATE meeting_sessions SET ended_at = ? WHERE id = ?",
        (ended_at.isoformat(), str(session.id)),
    )
    container.sessions.conn.commit()
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


async def _cancel(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_finalize_requested_returns_before_the_slow_work_completes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = _settings(tmp_path)
    container = _container(settings)
    sid = _seed_ended_all_unknown_session(container, ended_at=datetime(2026, 1, 1, 10, 0, 0))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    release = asyncio.Event()
    started = asyncio.Event()

    async def fake_finalize_offline(**kwargs):  # type: ignore[no-untyped-def]
        started.set()
        await release.wait()
        return 1

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await asyncio.wait_for(
            controller.handle(
                store, act.FinalizeSessionRequested(session_id=sid, at=datetime.now())
            ),
            timeout=1.0,
        )
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert "finalize:" + str(sid) in store.get_state().busy_operations

        release.set()
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=1.0)
        assert store.get_state().busy_operations == {}
    finally:
        release.set()
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_startup_recovery_enqueues_recent_all_unknown_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = _settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN="fake-token")
    container = _container(settings)
    recent_sid = _seed_ended_all_unknown_session(
        container, ended_at=datetime.utcnow() - timedelta(hours=1)
    )
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id, **kwargs):  # type: ignore[no-untyped-def]
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now()))
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=1.0)
        assert finalized == [recent_sid]
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_startup_recovery_skipped_without_hf_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = _settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN=None)
    container = _container(settings)
    _seed_ended_all_unknown_session(container, ended_at=datetime.utcnow() - timedelta(hours=1))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id, **kwargs):  # type: ignore[no-untyped-def]
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now()))
        await asyncio.sleep(0.05)
        assert finalized == []
    finally:
        await _cancel(controller._finalize_worker_task)


@pytest.mark.asyncio
async def test_startup_recovery_skips_sessions_ended_outside_the_recovery_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = _settings(tmp_path, FINALIZE_ON_SESSION_STOP=True, HF_TOKEN="fake-token")
    container = _container(settings)
    _seed_ended_all_unknown_session(container, ended_at=datetime.utcnow() - timedelta(days=10))
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    finalized: list[UUID] = []

    async def fake_finalize_offline(*, session_id, **kwargs):  # type: ignore[no-untyped-def]
        finalized.append(session_id)
        return 0

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        await controller.handle(store, act.AppStarted(at=datetime.now()))
        await asyncio.sleep(0.05)
        assert finalized == []
    finally:
        await _cancel(controller._finalize_worker_task)
