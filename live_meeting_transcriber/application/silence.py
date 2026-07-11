"""Silence-skip decision for live transcription chunks (F1, FEAT-01).

Quiet chunks waste transcription tokens (OpenAI) or compute (faster-whisper).
The decision is a pure predicate on the chunk's RMS energy in dBFS — no VAD
model, no provider imports, no I/O. Energy measurement itself lives in
``audio/wav_level.py``; the recorder feeds the measured level in here.

The policy is deliberately conservative: skipping real speech is far worse
than transcribing silence, so an unmeasurable level (NaN) never skips and the
threshold boundary keeps the chunk.
"""

from __future__ import annotations


def should_skip_silent_chunk(*, enabled: bool, rms_dbfs: float, threshold_dbfs: float) -> bool:
    """True when live transcription of this chunk should be skipped as silence.

    Skips only when enabled and the chunk is *strictly* quieter than the
    threshold. ``NaN`` compares false, so an unmeasurable level fails open.
    """
    return enabled and rms_dbfs < threshold_dbfs
