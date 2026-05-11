"""Domain-level errors for cross-layer handling (no UI imports)."""


class EmptyTranscriptionError(Exception):
    """Transcription produced no usable text (silent chunk, very short clip, or provider quirk).

    Callers should treat this as **recoverable**: skip persisting a segment and continue recording.
    """
