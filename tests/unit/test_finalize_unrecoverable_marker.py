"""B3 — startup auto-recovery stays ON, but unrecoverable finalize failures stop retrying.

B2's startup recovery re-enqueues recently-ended all-"unknown" sessions on every
launch. When finalize *cannot* succeed (whisperx extra not installed, recorded
audio gone), that meant one guaranteed error line per launch for 24h. B3 adds a
durable per-session marker: an unrecoverable failure writes it, startup recovery
skips marked sessions (with a single aggregate notice, not per-session spam), a
later successful finalize clears it, and the explicit ``finalize-pending`` CLI
deliberately ignores it (explicit user intent beats the marker) with a note.

Classification is conservative: only failures that provably cannot heal by
retrying (missing whisperx extra; recorded audio missing for an *ended* session)
are marked. Auth/network/OOM errors reach the handler as generic exceptions and
stay retryable — misclassifying a transient blip would silently disable recovery.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import live_meeting_transcriber.cli.main as cli_main
import pytest
from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.finalize_service import (
    classify_unrecoverable_finalize_error,
    clear_finalize_unrecoverable_marker,
    finalize_session_sync,
    mark_finalize_unrecoverable,
    read_finalize_unrecoverable_marker,
)
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession, TranscriptSegment
from live_meeting_transcriber.domain.session_audio import finalize_unrecoverable_marker_path
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.store import Store
from typer.testing import CliRunner

from tests.unit.conftest import build_sqlite_container, spy_dispatch, sqlite_test_settings

# --------------------------------------------------------------------------
# Classification: which failures are unrecoverable?
# --------------------------------------------------------------------------


def test_missing_whisperx_extra_is_unrecoverable() -> None:
    cause = classify_unrecoverable_finalize_error(
        ImportError("No module named 'whisperx'"), session_ended=True
    )
    assert cause is not None
    assert "whisperx" in cause


def test_missing_whisperx_extra_is_unrecoverable_even_mid_recording() -> None:
    # The extra doesn't appear by itself, ended or not.
    assert (
        classify_unrecoverable_finalize_error(ImportError("nope"), session_ended=False) is not None
    )


def test_missing_audio_for_ended_session_is_unrecoverable() -> None:
    cause = classify_unrecoverable_finalize_error(
        FileNotFoundError("/x/full_session.wav"), session_ended=True
    )
    assert cause is not None
    assert "audio" in cause.lower()


def test_missing_audio_while_still_recording_is_transient() -> None:
    # Speaker ID pressed before the first chunk flushed: the WAV will appear.
    assert (
        classify_unrecoverable_finalize_error(FileNotFoundError("x"), session_ended=False) is None
    )


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("bad value(s) in fds_to_keep"),
        OSError("network is unreachable"),
        ValueError("401 Client Error: invalid HF token"),
        MemoryError(),
    ],
)
def test_other_failures_stay_retryable(exc: BaseException) -> None:
    # Auth/network/OOM arrive as generic exceptions — stay conservative and retry.
    assert classify_unrecoverable_finalize_error(exc, session_ended=True) is None


# --------------------------------------------------------------------------
# Marker IO: durable, inspectable sidecar in the session's data dir
# --------------------------------------------------------------------------


def test_mark_then_read_round_trips_and_is_inspectable_json(tmp_path: Path) -> None:
    sid = uuid4()
    mark_finalize_unrecoverable(
        data_dir=tmp_path, session_id=sid, cause="whisperx extra missing", error="ImportError: x"
    )

    marker = read_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=sid)
    assert marker is not None
    assert marker.cause == "whisperx extra missing"
    assert marker.error == "ImportError: x"
    assert marker.marked_at  # timestamped for the operator

    # Lives next to full_session.wav and is plain JSON an operator can cat/delete.
    path = finalize_unrecoverable_marker_path(tmp_path / "sessions" / str(sid))
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["cause"] == "whisperx extra missing"


def test_read_returns_none_when_unmarked(tmp_path: Path) -> None:
    assert read_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=uuid4()) is None


def test_clear_removes_marker_and_is_idempotent(tmp_path: Path) -> None:
    sid = uuid4()
    mark_finalize_unrecoverable(data_dir=tmp_path, session_id=sid, cause="c", error="e")
    clear_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=sid)
    assert read_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=sid) is None
    clear_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=sid)  # no raise


def test_corrupt_marker_is_treated_as_unmarked(tmp_path: Path) -> None:
    # A mangled marker must never permanently disable recovery — fail open (retry).
    sid = uuid4()
    path = finalize_unrecoverable_marker_path(tmp_path / "sessions" / str(sid))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_finalize_unrecoverable_marker(data_dir=tmp_path, session_id=sid) is None


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


def _seed_session(
    container: Container, *, title: str = "m", ended: bool = True, speaker: str = "unknown"
) -> UUID:
    session = MeetingSession(title=title, started_at=datetime.now(UTC) - timedelta(hours=2))
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
    if ended:
        container.sessions.end(session.id)
    return session.id


def _patch_data_dir(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Settings, "ensure_data_dir", lambda self: data_dir)
    return data_dir


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# --------------------------------------------------------------------------
# Success clears the marker (shared service path: TUI worker and CLI both hit it)
# --------------------------------------------------------------------------


class _StubOfflineTranscriber:
    def transcribe_session(self, **kwargs: object) -> list[TranscriptSegment]:
        session_id = kwargs["session_id"]
        assert isinstance(session_id, UUID)
        now = datetime.now(UTC)
        return [
            TranscriptSegment(
                session_id=session_id,
                started_at=now,
                ended_at=now + timedelta(seconds=1),
                text="fixed",
                speaker="SPEAKER_00",
            )
        ]


def test_successful_finalize_clears_the_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container)
    # The wav must exist for finalize to load inputs.
    wav_dir = data_dir / "sessions" / str(sid)
    wav_dir.mkdir(parents=True, exist_ok=True)
    (wav_dir / "full_session.wav").write_bytes(b"RIFF")
    mark_finalize_unrecoverable(data_dir=data_dir, session_id=sid, cause="c", error="e")
    monkeypatch.setattr(Container, "offline_transcriber", lambda self: _StubOfflineTranscriber())

    n = finalize_session_sync(container=container, settings=settings, session_id=sid)

    assert n == 1
    assert read_finalize_unrecoverable_marker(data_dir=data_dir, session_id=sid) is None


# --------------------------------------------------------------------------
# Controller: unrecoverable failures write the marker + say "won't auto-retry"
# --------------------------------------------------------------------------


def _controller(settings: Settings, container: Container) -> tuple[Store, TuiController]:
    store = Store()
    return store, TuiController(store=store, container=container, settings=settings)


@pytest.mark.asyncio
async def test_import_error_writes_marker_and_failure_says_wont_auto_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container)
    store, controller = _controller(settings, container)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(**kwargs: object) -> int:
        raise ImportError("No module named 'whisperx'")

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

    marker = read_finalize_unrecoverable_marker(data_dir=data_dir, session_id=sid)
    assert marker is not None, "missing whisperx extra must set the won't-retry marker"
    failed = [a for a in dispatched if isinstance(a, act.FinalizeSessionFailed)]
    assert len(failed) == 1
    msg = failed[0].message.lower()
    assert "won't auto-retry" in msg
    assert "finalize-pending" in msg
    assert "doctor" in msg  # cross-reference the F9 diagnosis command


@pytest.mark.asyncio
async def test_missing_wav_on_ended_session_writes_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, ended=True)
    store, controller = _controller(settings, container)

    async def fake_finalize_offline(**kwargs: object) -> int:
        raise FileNotFoundError("full_session.wav")

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

    assert read_finalize_unrecoverable_marker(data_dir=data_dir, session_id=sid) is not None


@pytest.mark.asyncio
async def test_missing_wav_while_still_recording_does_not_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Speaker ID pressed before the first chunk flushed: the WAV appears later —
    # marking here could wrongly suppress recovery for a session that heals itself.
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container, ended=False)
    store, controller = _controller(settings, container)

    async def fake_finalize_offline(**kwargs: object) -> int:
        raise FileNotFoundError("full_session.wav")

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

    assert read_finalize_unrecoverable_marker(data_dir=data_dir, session_id=sid) is None


@pytest.mark.asyncio
async def test_transient_failure_does_not_mark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    sid = _seed_session(container)
    store, controller = _controller(settings, container)

    async def fake_finalize_offline(**kwargs: object) -> int:
        raise RuntimeError("CUDA out of memory")

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

    assert read_finalize_unrecoverable_marker(data_dir=data_dir, session_id=sid) is None


# --------------------------------------------------------------------------
# Startup recovery: skips marked sessions with ONE aggregate notice
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_skips_marked_sessions_and_logs_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path, finalize_on_session_stop=True, hf_token="hf_x")
    container = build_sqlite_container(settings)
    marked_a = _seed_session(container, title="marked A")
    marked_b = _seed_session(container, title="marked B")
    healthy = _seed_session(container, title="retry me")
    for sid in (marked_a, marked_b):
        mark_finalize_unrecoverable(
            data_dir=data_dir, session_id=sid, cause="whisperx extra missing", error="ImportError"
        )
    store, controller = _controller(settings, container)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(**kwargs: object) -> int:
        return 1

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        controller._recover_unfinalized_sessions(store)
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
    finally:
        await _cancel(controller._finalize_worker_task)

    queued = [a.session_id for a in dispatched if isinstance(a, act.FinalizeSessionQueued)]
    assert queued == [healthy], "marked sessions must not be re-enqueued at startup"
    skip_lines = [
        a
        for a in dispatched
        if isinstance(a, act.UiLogLineAdded) and "finalize-pending" in a.message
    ]
    assert len(skip_lines) == 1, "one aggregate skip notice, not per-session spam"
    assert "2" in skip_lines[0].message
    assert "doctor" in skip_lines[0].message


@pytest.mark.asyncio
async def test_recovery_with_no_marked_sessions_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path, finalize_on_session_stop=True, hf_token="hf_x")
    container = build_sqlite_container(settings)
    healthy = _seed_session(container, title="retry me")
    store, controller = _controller(settings, container)
    dispatched = spy_dispatch(store)

    async def fake_finalize_offline(**kwargs: object) -> int:
        return 1

    monkeypatch.setattr(
        "live_meeting_transcriber.application.finalize_service.finalize_session_offline",
        fake_finalize_offline,
    )

    try:
        controller._recover_unfinalized_sessions(store)
        await asyncio.wait_for(controller._finalize_queue.join(), timeout=2.0)
    finally:
        await _cancel(controller._finalize_worker_task)

    queued = [a.session_id for a in dispatched if isinstance(a, act.FinalizeSessionQueued)]
    assert queued == [healthy]
    assert not [
        a
        for a in dispatched
        if isinstance(a, act.UiLogLineAdded) and "finalize-pending" in a.message
    ]


# --------------------------------------------------------------------------
# CLI finalize-pending: explicit user intent beats the marker
# --------------------------------------------------------------------------


def test_finalize_pending_ignores_marker_with_a_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = _patch_data_dir(monkeypatch, tmp_path / "data")
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    marked = _seed_session(container, title="marked")
    unmarked = _seed_session(container, title="unmarked")
    mark_finalize_unrecoverable(
        data_dir=data_dir, session_id=marked, cause="whisperx extra missing", error="ImportError"
    )
    monkeypatch.setattr(cli_main, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_main, "build_container", lambda _s: container)

    result = CliRunner().invoke(cli_main.app, ["finalize-pending", "--dry-run"])

    assert result.exit_code == 0
    assert str(marked) in result.output, "explicit CLI run must still include marked sessions"
    assert str(unmarked) in result.output
    assert "retrying anyway" in result.output.lower()
    assert "1" in result.output  # how many are marked
