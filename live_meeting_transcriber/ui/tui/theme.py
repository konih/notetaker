"""Notetaker design system: the custom Textual theme and shared color tokens.

One place owns every color the TUI uses. The Textual :class:`Theme` drives all
``$primary``/``$accent``/… CSS variables; the module-level tokens are for Rich
markup built in Python (VU meter zones, speaker chips, state pills) where CSS
variables are not available. Both draw from the same palette so the app reads
as one designed surface, not a collage.

Palette: a deep charcoal-navy base with periwinkle/cyan accents and warm
signal colors (inspired by Tokyo Night) — high contrast for live-status
glanceability without neon glare during long meetings.
"""

from __future__ import annotations

from textual.theme import Theme

# --- base palette -----------------------------------------------------------

BACKGROUND = "#0e1117"
SURFACE = "#151a24"
PANEL = "#1b2130"
FOREGROUND = "#c8d3f5"

PRIMARY = "#7aa2f7"  # periwinkle — chrome, borders, focus
SECONDARY = "#bb9af7"  # violet — card titles, secondary emphasis
ACCENT = "#7dcfff"  # cyan — live data, highlights
SUCCESS = "#9ece6a"
WARNING = "#e0af68"
ERROR = "#f7768e"

# --- semantic tokens (Rich markup in Python renderers) -----------------------

# Recording-state signal colors (state pill, transcript border, deck accents).
STATE_RECORDING = ERROR  # rose — universally "live/recording"
STATE_BUSY = WARNING  # amber — starting/stopping transitions
STATE_OK = PRIMARY  # periwinkle — stopped cleanly
STATE_FAILED = "#db4b4b"  # deep red — hard failure
PILL_INK = "#0e1117"  # text/glyph color on filled pills

# VU meter zones (fraction of full scale → color).
LEVEL_OK = SUCCESS
LEVEL_HOT = WARNING
LEVEL_PEAK = ERROR

# Stable per-speaker chip colors. Assignment hashes the speaker *key*, so a
# speaker keeps their color across re-renders, tabs, and sessions.
SPEAKER_PALETTE: tuple[str, ...] = (
    "#7aa2f7",  # periwinkle
    "#f7768e",  # rose
    "#9ece6a",  # green
    "#e0af68",  # amber
    "#bb9af7",  # violet
    "#7dcfff",  # cyan
    "#ff9e64",  # orange
    "#2ac3de",  # teal
)

NOTETAKER_DARK = Theme(
    name="notetaker-dark",
    primary=PRIMARY,
    secondary=SECONDARY,
    accent=ACCENT,
    foreground=FOREGROUND,
    background=BACKGROUND,
    surface=SURFACE,
    panel=PANEL,
    success=SUCCESS,
    warning=WARNING,
    error=ERROR,
    dark=True,
)
