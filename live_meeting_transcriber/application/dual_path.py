"""Shared predicate + downgrade reason for ``AUDIO_STEREO_MODE=dual_path`` (D4).

``dual_path`` splits a 2-channel chunk into mic (L) and system (R) and transcribes each
leg separately for channel-based speaker keys. That only works when the transcriber
implements the optional ``transcribe_stereo_chunk`` capability (faster-whisper today) and
capture is actually stereo. When either precondition is missing, recording silently falls
back to a mono mixdown.

Both the recorder's per-chunk path and the up-front startup checks (CLI ``record`` /
TUI launch) import these helpers so the two can never disagree about when dual_path is
effective. This module depends on nothing below the application layer — it only duck-types
the optional capability on the transcription port.
"""

from __future__ import annotations


def transcriber_supports_dual_path(transcriber: object) -> bool:
    """True when ``transcriber`` can transcribe mic/system legs separately."""
    return callable(getattr(transcriber, "transcribe_stereo_chunk", None))


def dual_path_downgrade_reason(
    *, audio_stereo_mode: str, audio_channels: int, transcriber: object
) -> str | None:
    """Explain why a requested ``dual_path`` will be ignored, or ``None`` if it is effective.

    Returns an operator-facing message (safe for stderr / the warnings panel) when
    dual_path is configured but a precondition is unmet; ``None`` when the mode is not
    dual_path or dual_path will actually run.
    """
    if audio_stereo_mode != "dual_path":
        return None
    if audio_channels != 2:
        return (
            f"AUDIO_STEREO_MODE=dual_path needs AUDIO_CHANNELS=2 (got {audio_channels}); "
            "per-speaker channels are disabled and audio is mixed to mono."
        )
    if not transcriber_supports_dual_path(transcriber):
        return (
            "AUDIO_STEREO_MODE=dual_path requires TRANSCRIPTION_PROVIDER=faster_whisper; "
            "per-speaker channels are disabled and audio is mixed to mono."
        )
    return None
