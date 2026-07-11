"""F6 — screen-capture events surface in the TUI (bridge → reducer → sidebar)."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.effects.controller import TuiController, settings_loaded_action
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.reducer import reduce
from live_meeting_transcriber.ui.state.selectors import build_pipeline_card_lines
from live_meeting_transcriber.ui.state.store import Store

from tests.unit.conftest import build_sqlite_container, sqlite_test_settings

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


# --- bridge ---------------------------------------------------------------


def test_bridge_shot_taken_maps_to_shot_observed() -> None:
    sid = uuid4()
    actions = application_events_to_actions(
        ev.ScreenCaptureShotTaken(
            session_id=sid, path=Path("/tmp/capture_x.png"), shot_count=3, at=_NOW
        )
    )
    assert len(actions) == 1
    assert isinstance(actions[0], act.ScreenCaptureShotObserved)
    assert actions[0].shot_count == 3


def test_bridge_unavailable_maps_to_warning() -> None:
    actions = application_events_to_actions(
        ev.ScreenCaptureUnavailable(session_id=uuid4(), message="needs Screen Recording", at=_NOW)
    )
    assert len(actions) == 1
    assert isinstance(actions[0], act.WarningRaised)
    assert "Screen Recording" in actions[0].message


# --- reducer --------------------------------------------------------------


def test_reducer_counts_shots_and_resets_on_new_recording() -> None:
    state = reduce(initial_app_state(), act.ScreenCaptureShotObserved(shot_count=5, at=_NOW))
    assert state.screen_capture_shots == 5
    state = reduce(
        state,
        act.RecordingStarted(
            session_id=uuid4(),
            title="t",
            audio_source="s",
            microphone_source=None,
            chunk_seconds=10,
            at=_NOW,
        ),
    )
    assert state.screen_capture_shots == 0


def test_settings_loaded_action_carries_capture_enabled(tmp_path: Path) -> None:
    settings = sqlite_test_settings(tmp_path, live_screen_capture_enabled=True)
    action = settings_loaded_action(settings, _NOW)
    assert action.screen_capture_enabled is True
    state = reduce(initial_app_state(), action)
    assert state.screen_capture_enabled is True


# --- sidebar --------------------------------------------------------------


def test_pipeline_card_shows_capture_line_only_when_enabled() -> None:
    state = initial_app_state()
    assert not any("Capture" in line for line in build_pipeline_card_lines(state, _NOW))

    state = state.model_copy(update={"screen_capture_enabled": True, "screen_capture_shots": 3})
    capture_line = next(
        line for line in build_pipeline_card_lines(state, _NOW) if "Capture" in line
    )
    assert "3" in capture_line


# --- controller wiring ------------------------------------------------------


class _UnavailableScreen:
    def availability(self) -> tuple[bool, str | None]:
        return (False, "requires macOS")

    def capture(self, output_path: Path) -> bool:  # pragma: no cover - never reached
        return False


@pytest.mark.asyncio
async def test_controller_skips_capture_task_when_disabled(tmp_path: Path) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    controller = TuiController(store=Store(), container=container, settings=settings)
    assert controller.start_capture_task(uuid4(), lambda e: None) is None


@pytest.mark.asyncio
async def test_controller_starts_capture_task_when_enabled(tmp_path: Path) -> None:
    settings = sqlite_test_settings(tmp_path, live_screen_capture_enabled=True)
    container = dataclasses.replace(
        build_sqlite_container(settings), screen_capture=_UnavailableScreen()
    )
    controller = TuiController(store=Store(), container=container, settings=settings)
    events: list[ev.ApplicationEvent] = []
    task = controller.start_capture_task(uuid4(), events.append)
    assert task is not None
    await task
    assert len(events) == 1
    assert isinstance(events[0], ev.ScreenCaptureUnavailable)


@pytest.mark.asyncio
async def test_stop_recording_cancels_capture_task(tmp_path: Path) -> None:
    settings = sqlite_test_settings(tmp_path)
    container = build_sqlite_container(settings)
    store = Store()
    controller = TuiController(store=store, container=container, settings=settings)

    async def forever() -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(forever())
    controller._capture_task = task
    await controller.handle(act.RecordingStopRequested(at=_NOW), store)
    assert task.cancelled() or task.done()
    assert controller._capture_task is None
