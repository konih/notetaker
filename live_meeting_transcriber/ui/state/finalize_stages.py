"""Canonical offline Speaker ID / finalize pipeline stage ladder (F8).

The WhisperX progress hook emits free-form human messages; the deck's stage bar
needs a stable, ordered ladder to derive "how far along" from them. Shared by the
reducer (which folds messages into a monotonic high-water-mark index, so wording
drift can never run the bar backwards) and the selectors/renderer.
"""

from __future__ import annotations

FINALIZE_STAGES: tuple[str, ...] = ("load", "transcribe", "align", "diarize", "persist")

# Keyword → stage, checked in order: later-stage markers first so e.g.
# "Loading diarization model…" reads as diarize (not load). The terminal
# messages — "Diarization finished." / "Skipping diarization…" and the very
# last "WhisperX pass complete (N segment(s))." — read as persist: compute is
# over and the DB write is what happens next.
_STAGE_MARKERS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("diarization finished", "skipping diarization", "pass complete"), 4),
    (("diariz", "assigning speakers"), 3),
    (("align",), 2),
    (("transcrib",), 1),
)


def select_finalize_stage_index(stage: str | None) -> int:
    """Index into :data:`FINALIZE_STAGES` for a free-form finalize progress message.

    Unrecognized or missing messages (including the reducer's initial "starting…")
    classify as the earliest stage — the bar must degrade gracefully, never crash,
    when the pipeline's wording changes. The reducer additionally keeps a
    high-water mark so an unrecognized *late* message holds the bar in place.
    """
    if not stage:
        return 0
    lowered = stage.lower()
    for keywords, index in _STAGE_MARKERS:
        if any(k in lowered for k in keywords):
            return index
    return 0
