"""Domain-level errors for cross-layer handling (no UI imports)."""


class EmptyTranscriptionError(Exception):
    """Transcription produced no usable text (silent chunk, very short clip, or provider quirk).

    Callers should treat this as **recoverable**: skip persisting a segment and continue recording.
    """


class TranscriptionProviderError(Exception):
    """Transcription failed for a chunk (API error, corrupt audio, ffmpeg extract failure).

    ``recoverable`` tells callers whether recording can continue past this chunk. Transient,
    per-chunk failures (rate limits, a single corrupt clip) are recoverable and should be
    skipped; a non-recoverable error (e.g. misconfiguration that will fail every chunk) should
    propagate so the caller can stop. Adapters raise this domain type — the application layer
    branches on the flag and never imports provider-specific exception classes.
    """

    def __init__(self, *args: object, recoverable: bool = True) -> None:
        super().__init__(*args)
        self.recoverable = recoverable
