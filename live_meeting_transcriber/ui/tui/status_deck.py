"""The status deck — the redesigned top-of-app chrome.

Replaces the stock Textual ``Header`` with a live control-room strip: the
recording state pill (pulsing while recording), the meeting title, elapsed
time, a gradient VU meter, the level-history sparkline, and a clock. All
content comes from :func:`rendering.build_deck_markup`, a pure function of
``AppState`` + wall clock, so the widget itself stays a thin shell.

Per U19 the app name is *not* rendered here — the deck shows meeting context
only (app identity lives in the terminal title and command palette).
"""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from live_meeting_transcriber.ui.state.model import AppState, RecordingStatus
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.ui.tui.rendering import build_deck_markup
from live_meeting_transcriber.utils.time import to_local, utc_now


class StatusDeck(Horizontal):
    """One-row live status strip docked above the tab bar."""

    DEFAULT_CSS = """
    StatusDeck { height: 1; background: $panel; padding: 0 1; }
    StatusDeck #deck-main { width: 1fr; }
    StatusDeck #deck-clock { width: auto; color: $text-muted; padding-left: 1; }
    """

    # Pulse cadence: fast enough to read as "live", slow enough not to distract.
    _TICK_SECONDS = 0.5

    def __init__(self, *, store: Store) -> None:
        super().__init__(id="status-deck")
        self._store = store
        self._pulse_on = True
        self._unsub: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="deck-main", markup=True)
        yield Static("", id="deck-clock", markup=True)

    def on_mount(self) -> None:
        self._unsub = self._store.subscribe(lambda state: self._render_deck(state))
        self.set_interval(self._TICK_SECONDS, self._tick)
        self._render_deck(self._store.get_state())

    def on_unmount(self) -> None:
        if self._unsub is not None:
            self._unsub()

    def _tick(self) -> None:
        """Advance the pulse phase and re-render clock/elapsed/decay against the wall clock."""
        self._pulse_on = not self._pulse_on
        self._render_deck(self._store.get_state())

    def _render_deck(self, state: AppState) -> None:
        now = utc_now()
        # Pulse only animates while recording; otherwise the pill holds steady.
        pulse = self._pulse_on or state.recording_status != RecordingStatus.recording
        self.query_one("#deck-main", Static).update(build_deck_markup(state, now, pulse_on=pulse))
        self.query_one("#deck-clock", Static).update(to_local(now).strftime("%H:%M"))
