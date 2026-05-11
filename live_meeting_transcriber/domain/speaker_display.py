"""Human-readable speaker labels for transcript UI and exports."""

from __future__ import annotations


def format_transcript_speaker_label(speaker_key: str, display_map: dict[str, str] | None = None) -> str:
    """Map internal diarization keys and aliases to display text.

    - ``unknown`` → "Unknown Speaker"
    - ``speaker_N`` (1-based key) → "Speaker N" when no alias
    - Otherwise use ``display_map`` when present, else the raw key.
    """
    disp = display_map or {}
    if speaker_key in disp and disp[speaker_key].strip():
        return disp[speaker_key].strip()
    if speaker_key == "unknown":
        return "Unknown Speaker"
    if speaker_key.startswith("speaker_"):
        tail = speaker_key.removeprefix("speaker_")
        if tail.isdigit():
            return f"Speaker {int(tail)}"
    return speaker_key
