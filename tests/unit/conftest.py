"""Shared unit-test helpers (T4 consolidation).

Canonical copies of helpers that had drifted into per-file duplicates:

- ``write_silent_wav`` / ``write_wav`` — synthesized 16-bit PCM WAV builders
  (recorder, silence-skip, video-import, transcriber tests).
- ``make_mock_tui_container`` — the MagicMock ``Container`` used by TUI Pilot tests,
  with faithful list/get/delete semantics over an in-memory session list.
- ``make_tui_app`` / ``make_tui_harness`` — the Store + TuiController + TranscriberApp
  wiring block.
- ``sqlite_test_settings`` / ``build_sqlite_container`` — real-SQLite container with
  live session/transcript/diarization repositories (finalize/controller tests).
- ``spy_dispatch`` — records every action dispatched through a Store.

Deliberately NOT unified (differences are load-bearing): the int-sample WAV writers in
``test_diarization_wav_input.py`` / ``test_wav_level.py`` (exact sample values under
test), ``test_finalize_recovery.py``'s conn-injected container (drives raw SQL against
its own connection), and the per-file ``_app_with_live_session`` container mocks whose
``sessions.get``/``update_details`` shapes differ per scenario.

These are plain functions (imported via ``from tests.unit.conftest import ...``) rather
than fixtures so call sites keep explicit arguments; pytest imports this module once as
``tests.unit.conftest`` either way.
"""

from __future__ import annotations

import struct
import wave
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import MeetingSession
from live_meeting_transcriber.storage.repositories import (
    SqliteDiarizationRepository,
    SqliteMeetingSessionRepository,
    SqliteTranscriptRepository,
)
from live_meeting_transcriber.storage.sqlite import open_connection
from live_meeting_transcriber.ui.effects.controller import TuiController
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import initial_app_state
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.app import TranscriberApp

# --- synthesized WAV builders ----------------------------------------------------------


def write_silent_wav(
    path: Path, *, seconds: float = 2.0, rate: int = 16000, channels: int = 1
) -> Path:
    """Write ``seconds`` of digital silence as 16-bit PCM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * nframes * channels)
    return path


def write_wav(
    path: Path,
    samples: Sequence[float],
    *,
    sample_rate_hz: int = 16000,
    channels: int = 1,
) -> Path:
    """Write normalized [-1, 1] samples as a 16-bit PCM WAV."""
    ints = [max(-32768, min(32767, round(s * 32767))) for s in samples]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(struct.pack(f"<{len(ints)}h", *ints))
    return path


# --- TUI Pilot harness -----------------------------------------------------------------


def make_mock_tui_container(tmp_path: Path, sessions: Sequence[MeetingSession]) -> MagicMock:
    """MagicMock Container over an in-memory session list.

    ``sessions.list``/``get``/``delete`` behave like the real repository (lookup by id,
    delete removes from the list), so tests can assert refresh-after-delete flows.
    """
    store_list = list(sessions)
    c = MagicMock()
    c.sessions.list.side_effect = lambda: list(store_list)
    c.sessions.get.side_effect = lambda sid: next((s for s in store_list if s.id == sid), None)

    def _delete(sid: object) -> bool:
        before = len(store_list)
        store_list[:] = [s for s in store_list if s.id != sid]
        return len(store_list) < before

    c.sessions.delete.side_effect = _delete
    c.summaries.get_by_session.return_value = None
    c.transcripts.list_by_session.return_value = []
    c.session_speakers.get_map.return_value = {}
    c.settings.ensure_data_dir.return_value = tmp_path
    c.devices.list_sources.return_value = [object()]
    return c


def make_tui_harness(
    container: Container,
    *,
    state_updates: dict[str, object] | None = None,
    settings: Settings | None = None,
) -> tuple[TranscriberApp, Store, TuiController]:
    """Wire Store + TuiController + TranscriberApp the way the composition root does."""
    state = initial_app_state()
    if state_updates:
        state = state.model_copy(update=state_updates)
    store = Store(state=state)
    controller = TuiController(store=store, container=container, settings=settings or Settings())
    store.register_effects(controller.handle)
    app = TranscriberApp(store=store, container=container, controller=controller)
    return app, store, controller


def make_tui_app(
    container: Container,
    *,
    state_updates: dict[str, object] | None = None,
    settings: Settings | None = None,
) -> TranscriberApp:
    return make_tui_harness(container, state_updates=state_updates, settings=settings)[0]


# --- real-SQLite container (finalize/controller tests) -----------------------------------


def sqlite_test_settings(tmp_path: Path, **overrides: object) -> Settings:
    db = tmp_path / "test.sqlite3"
    return Settings(database_url=f"sqlite:////{db}", **overrides)  # type: ignore[arg-type]


def build_sqlite_container(settings: Settings) -> Container:
    """Container with live sqlite session/transcript/diarization repos, no providers.

    Summaries/people/session-speakers stay ``None`` — the finalize and controller tests
    exercise only the session + transcript + diarization paths.
    """
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


# --- misc -------------------------------------------------------------------------------


def spy_dispatch(store: Store) -> list[act.Action]:
    """Record every action dispatched through ``store`` while still applying it."""
    dispatched: list[act.Action] = []
    original = store.dispatch

    def spy(action: act.Action) -> None:
        dispatched.append(action)
        original(action)

    store.dispatch = spy  # type: ignore[method-assign]
    return dispatched
