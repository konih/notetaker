from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

import structlog

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.actions import Action
from live_meeting_transcriber.ui.state.model import AppState, initial_app_state
from live_meeting_transcriber.ui.state.reducer import reduce

Subscriber = Callable[[AppState], None]
Effect = Callable[["Store", Action], Awaitable[None]]


class Store:
    """Synchronous Redux-like store; async effects run separately."""

    def __init__(
        self,
        *,
        state: AppState | None = None,
        reducer: Callable[[AppState, Action], AppState] = reduce,
        effects: Sequence[Effect] | None = None,
    ) -> None:
        self._state = state or initial_app_state()
        self._reducer = reducer
        self._effects: list[Effect] = list(effects or ())
        self._subscribers: list[Subscriber] = []
        self._log = structlog.get_logger(component="ui_store")

    def register_effects(self, *effects: Effect) -> None:
        self._effects.extend(effects)

    def get_state(self) -> AppState:
        return self._state

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def dispatch(self, action: Action) -> None:
        # Log action name only — never transcript payload (DEBUG to keep INFO readable).
        self._log.debug("ui_dispatch", action=type(action).__name__)
        self._emit_structlog_for_user_visible_issues(action)
        self._state = self._reducer(self._state, action)
        for fn in list(self._subscribers):
            fn(self._state)

    def _emit_structlog_for_user_visible_issues(self, action: Action) -> None:
        """Mirror Live tab errors/warnings to the log file (they only hit the UI reducer otherwise)."""
        slog = structlog.get_logger(component="ui")
        if isinstance(action, act.ErrorRaised):
            slog.error("user_visible_error", message=action.message)
        elif isinstance(action, act.WarningRaised):
            slog.warning("user_visible_warning", message=action.message)
        elif isinstance(action, act.RecordingFailed):
            slog.error("user_visible_error", message=action.message, source="recording")

    async def dispatch_with_effects(self, action: Action) -> None:
        self.dispatch(action)
        for eff in list(self._effects):
            await eff(self, action)
