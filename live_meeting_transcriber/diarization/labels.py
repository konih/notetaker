"""Normalize external diarization labels to internal storage keys."""


def normalize_pyannote_speaker_label(raw: str) -> str:
    """Map Hugging Face / pyannote labels (e.g. ``SPEAKER_00``) to internal ``speaker_N`` keys."""
    u = raw.strip().upper().replace(" ", "_")
    if u.startswith("SPEAKER_"):
        tail = u[8:]
        try:
            idx = int(tail)
        except ValueError:
            return raw.strip().lower().replace(" ", "_")
        return f"speaker_{idx + 1}"
    return raw.strip().lower().replace(" ", "_")
