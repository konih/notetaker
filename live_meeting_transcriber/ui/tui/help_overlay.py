"""U16 — the ``?`` help overlay's content, derived from the live keybindings.

Keeping the help content a pure projection of the real ``BINDINGS`` lists means it
cannot drift out of sync: add, remove, or rename a binding and the overlay updates
for free — there is no second hand-maintained keymap table to keep aligned. This is
what lets the U4 footer stay tiny (only the core recording actions) without hiding
the overflow shortcuts: they are all still listed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BindingLike(Protocol):
    """The subset of Textual's ``Binding`` the overlay reads (duck-typed for tests)."""

    key: str
    description: str


@dataclass(frozen=True)
class HelpRow:
    """One shortcut: its (humanized) key(s) and what it does."""

    keys: str
    label: str


@dataclass(frozen=True)
class HelpSection:
    """A titled group of shortcuts (e.g. ``Global`` vs ``Meetings tab``)."""

    title: str
    rows: tuple[HelpRow, ...]


# Textual key *names* that should render as their user-facing symbol/word.
_SPECIAL_KEYS = {
    "question_mark": "?",
    "escape": "Esc",
    "space": "Space",
    "up": "↑",
    "down": "↓",
    "left": "←",
    "right": "→",
}


def humanize_key(key: str) -> str:
    """Render a Textual key name as a user-facing shortcut (``ctrl+d`` → ``Ctrl+D``).

    A binding may list several keys (``escape,q``); those render slash-joined.
    """
    parts: list[str] = []
    for single in key.split(","):
        single = single.strip()
        if not single:
            continue
        if single in _SPECIAL_KEYS:
            parts.append(_SPECIAL_KEYS[single])
            continue
        chunks: list[str] = []
        for chunk in single.split("+"):
            if chunk == "ctrl":
                chunks.append("Ctrl")
            elif len(chunk) == 1:
                chunks.append(chunk.upper())
            else:
                chunks.append(chunk.capitalize())
        parts.append("+".join(chunks))
    return " / ".join(parts)


def rows_from_bindings(bindings: object) -> tuple[HelpRow, ...]:
    """Project an iterable of Textual ``Binding``-like objects into help rows.

    Bindings without a key or a user-facing description are skipped (internal/hidden
    handlers with nothing meaningful to show). ``show`` is intentionally *not*
    consulted — overflow bindings hidden from the footer are the ones users most need
    the overlay to surface.
    """
    rows: list[HelpRow] = []
    for b in bindings:  # type: ignore[attr-defined]
        key = getattr(b, "key", "") or ""
        label = getattr(b, "description", "") or ""
        if not key or not label:
            continue
        rows.append(HelpRow(humanize_key(key), str(label)))
    return tuple(rows)


def build_help_sections(
    global_bindings: object, meetings_bindings: object
) -> tuple[HelpSection, ...]:
    """Build the overlay's sections from the app's global + Meetings-tab bindings."""
    return (
        HelpSection("Global", rows_from_bindings(global_bindings)),
        HelpSection("Meetings tab", rows_from_bindings(meetings_bindings)),
    )


def format_help_markup(sections: tuple[HelpSection, ...]) -> str:
    """Render the sections as Textual/Rich console markup for a ``Static``.

    Keys render as reverse-video "keycaps" aligned per section, so the overlay
    scans like a keyboard cheat-sheet rather than a text dump.
    """
    lines: list[str] = []
    for section in sections:
        lines.append(f"[bold]{section.title}[/]")
        width = max((len(row.keys) for row in section.rows), default=0)
        for row in section.rows:
            # Pad *outside* the reverse block so each key renders as a snug
            # keycap, with the labels still aligned in a column.
            pad = " " * (width - len(row.keys))
            lines.append(f"  [reverse] {row.keys} [/reverse]{pad}  {row.label}")
        lines.append("")
    return "\n".join(lines).rstrip()
