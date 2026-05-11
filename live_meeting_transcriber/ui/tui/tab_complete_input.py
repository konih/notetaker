"""Input that accepts Tab to apply the ghost completion (full suggestion) when at end of text."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input


class TabCompletableInput(Input):
    """Tab applies the visible suggestion (same as Right); otherwise moves focus forward."""

    BINDINGS = [
        *Input.BINDINGS,
        Binding("tab", "accept_completion_or_focus_next", show=False, priority=True),
    ]

    def action_accept_completion_or_focus_next(self) -> None:
        if self.cursor_at_end and self._suggestion:
            self.value = self._suggestion
            self.cursor_position = len(self.value)
            self._suggestion = ""
        else:
            self.screen.focus_next()
