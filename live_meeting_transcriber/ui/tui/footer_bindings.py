"""U4 — single source of truth for the global footer binding catalog.

The always-visible footer used to show all fourteen global actions, which clips
well past a standard terminal width. This module splits those actions into a
small *core* set (shown in the footer, one keystroke away) and an *overflow* set
(hidden from the footer, still bound to their keys and surfaced in the command
palette). Keeping the split as pure data lets ``TranscriberApp.BINDINGS``, the
command palette, and the tests share one definition.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FooterAction:
    """One global action and how it should surface in the footer/palette."""

    key: str
    action: str
    label: str
    core: bool
    priority: bool = False


# Ordered as they should appear (core first, then overflow). ``core`` entries are
# the high-frequency recording workflow: start/stop a recording, wrap it up
# (summarize/export), and quit. Everything else is reachable by key and listed in
# the command palette (see ``TranscriberApp.get_system_commands``).
FOOTER_ACTIONS: tuple[FooterAction, ...] = (
    FooterAction("q", "quit", "Quit", core=True),
    FooterAction("r", "record", "Record", core=True),
    FooterAction("x", "stop", "Stop", core=True),
    FooterAction("k", "summarize", "Summarize", core=True, priority=True),
    FooterAction("w", "export_md", "Export", core=True, priority=True),
    FooterAction("t", "name_speakers", "Name speakers", core=False),
    FooterAction("s", "settings", "Settings", core=False),
    FooterAction("a", "audio_sources", "Audio sources", core=False),
    # `j` (jump to a meeting), not `m`: the Meetings tab binds `m` to its
    # More-actions menu (U9), which shadowed a global `m` there so the same key
    # meant two different things depending on the region (U12).
    FooterAction("j", "sessions", "Sessions", core=False),
    FooterAction("c", "ack_errors", "Ack errors", core=False),
    # ctrl+d, not ctrl+i: ctrl+i is byte-identical to Tab (0x09) on terminals without
    # the kitty keyboard protocol, so a ctrl+i binding never fires (it arrives as Tab).
    FooterAction("ctrl+d", "finalize_speakers", "Speaker ID", core=False, priority=True),
    FooterAction("ctrl+1", "focus_live_tab", "Live tab", core=False),
    FooterAction("ctrl+2", "focus_meetings_tab", "Meetings tab", core=False),
    FooterAction("ctrl+3", "focus_logs_tab", "Logs tab", core=False),
    # `?` opens the full keymap overlay (U16). Overflow, but the well-known
    # convention means users reach for it; it is also listed in the palette.
    FooterAction("question_mark", "help", "Help", core=False),
)


def core_footer_actions() -> tuple[FooterAction, ...]:
    """Actions shown in the always-visible footer."""
    return tuple(a for a in FOOTER_ACTIONS if a.core)


def overflow_footer_actions() -> tuple[FooterAction, ...]:
    """Actions hidden from the footer but still key-bound and in the palette."""
    return tuple(a for a in FOOTER_ACTIONS if not a.core)


def footer_key(action: str) -> str:
    """Canonical key for a global action — the single source for inline hints (U12).

    Hint strings rendered elsewhere (e.g. the Meetings tab header) must derive their
    keys from the catalog through this lookup so they cannot drift from the real
    bindings.
    """
    for a in FOOTER_ACTIONS:
        if a.action == action:
            return a.key
    raise KeyError(f"no footer action named {action!r}")
