"""F6 — live screen-capture loop (application layer, port-driven).

The loop is privacy-gated (no-ops when disabled), degrades gracefully when the
platform cannot capture (one warning event, then stops — never crashes the
recording), and journals every shot into ``sessions/<id>/screenshots/captures.json``
so exports can interleave the images with the transcript.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.live_capture import LiveScreenCaptureLoop
from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    ScreenCaptureShotTaken,
    ScreenCaptureUnavailable,
)
from live_meeting_transcriber.domain.session_audio import (
    live_captures_dir,
    live_captures_manifest_path,
    session_audio_dir,
)


class FakeScreen:
    """ScreenCapture port fake: scripted availability and per-shot results."""

    def __init__(
        self,
        *,
        available: tuple[bool, str | None] = (True, None),
        results: list[bool] | None = None,
    ) -> None:
        self._available = available
        self._results = results if results is not None else [True] * 100
        self.capture_paths: list[Path] = []

    def availability(self) -> tuple[bool, str | None]:
        return self._available

    def capture(self, output_path: Path) -> bool:
        self.capture_paths.append(output_path)
        ok = self._results[len(self.capture_paths) - 1]
        if ok:
            output_path.write_bytes(b"\x89PNG fake")
        return ok


def _sleeper_stopping_after(n_sleeps: int) -> Callable[[float], Awaitable[None]]:
    """An injected sleeper that lets the loop iterate ``n_sleeps`` times, then cancels."""
    count = 0

    async def sleeper(seconds: float) -> None:
        nonlocal count
        count += 1
        if count > n_sleeps:
            raise asyncio.CancelledError

    return sleeper


def _loop(
    tmp_path: Path,
    screen: FakeScreen,
    *,
    enabled: bool = True,
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> LiveScreenCaptureLoop:
    if sleeper is None:
        return LiveScreenCaptureLoop(
            screen=screen, data_dir=tmp_path, enabled=enabled, interval_seconds=60
        )
    return LiveScreenCaptureLoop(
        screen=screen, data_dir=tmp_path, enabled=enabled, interval_seconds=60, sleeper=sleeper
    )


@pytest.mark.asyncio
async def test_disabled_loop_is_a_noop(tmp_path: Path) -> None:
    screen = FakeScreen()
    events: list[ApplicationEvent] = []
    await _loop(tmp_path, screen, enabled=False).run(
        session_id=uuid4(), on_application_event=events.append
    )
    assert screen.capture_paths == []
    assert events == []


@pytest.mark.asyncio
async def test_unavailable_platform_warns_once_and_stops(tmp_path: Path) -> None:
    screen = FakeScreen(available=(False, "live screen capture requires macOS"))
    events: list[ApplicationEvent] = []
    sid = uuid4()
    await _loop(tmp_path, screen).run(session_id=sid, on_application_event=events.append)
    assert screen.capture_paths == []
    (event,) = events
    assert isinstance(event, ScreenCaptureUnavailable)
    assert event.session_id == sid
    assert "macOS" in event.message


@pytest.mark.asyncio
async def test_captures_periodically_and_journals_manifest(tmp_path: Path) -> None:
    screen = FakeScreen()
    events: list[ApplicationEvent] = []
    sid = uuid4()
    with pytest.raises(asyncio.CancelledError):
        await _loop(tmp_path, screen, sleeper=_sleeper_stopping_after(1)).run(
            session_id=sid, on_application_event=events.append
        )

    captures = live_captures_dir(session_audio_dir(tmp_path, sid))
    pngs = sorted(p.name for p in captures.glob("*.png"))
    assert len(pngs) == 2  # first shot immediately, second after one interval

    manifest = json.loads(live_captures_manifest_path(session_audio_dir(tmp_path, sid)).read_text())
    assert [item["path"] for item in manifest] == pngs
    for item in manifest:
        datetime.fromisoformat(item["captured_at"])  # parseable timestamps

    shots = [e for e in events if isinstance(e, ScreenCaptureShotTaken)]
    assert [s.shot_count for s in shots] == [1, 2]
    assert all(s.session_id == sid for s in shots)


@pytest.mark.asyncio
async def test_capture_failure_warns_and_stops_the_loop(tmp_path: Path) -> None:
    # TCC denial / broken binary: degrade with one warning, never crash recording.
    screen = FakeScreen(results=[True, False])
    events: list[ApplicationEvent] = []
    sid = uuid4()
    await _loop(tmp_path, screen, sleeper=_sleeper_stopping_after(99)).run(
        session_id=sid, on_application_event=events.append
    )  # returns (does not raise) because the loop stops itself on failure

    shots = [e for e in events if isinstance(e, ScreenCaptureShotTaken)]
    warnings = [e for e in events if isinstance(e, ScreenCaptureUnavailable)]
    assert len(shots) == 1
    assert len(warnings) == 1
    assert "Screen Recording" in warnings[0].message  # points at the TCC permission


@pytest.mark.asyncio
async def test_resumed_session_appends_to_existing_manifest(tmp_path: Path) -> None:
    sid = uuid4()
    root = session_audio_dir(tmp_path, sid)
    captures = live_captures_dir(root)
    captures.mkdir(parents=True, exist_ok=True)
    (captures / "capture_20260711T090000Z_000.png").write_bytes(b"old")
    live_captures_manifest_path(root).write_text(
        json.dumps(
            [
                {
                    "path": "capture_20260711T090000Z_000.png",
                    "captured_at": "2026-07-11T09:00:00+00:00",
                }
            ]
        )
    )

    screen = FakeScreen()
    with pytest.raises(asyncio.CancelledError):
        await _loop(tmp_path, screen, sleeper=_sleeper_stopping_after(0)).run(
            session_id=sid, on_application_event=None
        )

    manifest = json.loads(live_captures_manifest_path(root).read_text())
    assert len(manifest) == 2  # old entry kept, new shot appended
    names = [item["path"] for item in manifest]
    assert len(set(names)) == 2  # no filename collision with the previous run
