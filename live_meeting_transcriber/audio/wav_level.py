from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def peak_linear_from_wav_path(path: Path) -> float:
    """Peak absolute sample normalized to 0..1 for PCM WAV (common ffmpeg output: s16le)."""
    with wave.open(str(path), "rb") as w:
        sampwidth = w.getsampwidth()
        nframes = w.getnframes()
        if nframes == 0 or sampwidth not in (1, 2, 4):
            return 0.0
        frames = w.readframes(nframes)

    if sampwidth == 2:
        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        peak = max(abs(x) for x in samples) if samples else 0
        return min(1.0, peak / 32768.0)

    if sampwidth == 1:
        # unsigned 8-bit
        peak = max(abs(x - 128) for x in frames) if frames else 0
        return min(1.0, peak / 128.0)

    # 32-bit float — rare for our pipeline; best-effort
    samples_f = struct.unpack(f"<{len(frames) // 4}f", frames)
    peak_f = max(abs(x) for x in samples_f) if samples_f else 0.0
    return min(1.0, peak_f)


def rms_dbfs_from_wav_path(path: Path) -> float:
    """Overall RMS level in dBFS (<= 0.0) for PCM WAV; ``-inf`` for digital silence.

    Dependency-free energy measurement across all channels — the input to the
    silence-skip decision (F1). Raises ``wave.Error``/``OSError`` on unreadable
    files; callers decide the failure policy (the recorder fails open).
    """
    with wave.open(str(path), "rb") as w:
        sampwidth = w.getsampwidth()
        nframes = w.getnframes()
        if nframes == 0 or sampwidth not in (1, 2, 4):
            return float("-inf")
        frames = w.readframes(nframes)

    return _rms_dbfs_from_frames(frames, sampwidth)


def rms_dbfs_window_from_wav_path(path: Path, start_seconds: float, end_seconds: float) -> float:
    """RMS level in dBFS of ``[start_seconds, end_seconds)`` of a PCM WAV; ``-inf``
    for digital silence, degenerate windows, or windows entirely past EOF.

    Windows are clamped to the file, so a segment end that overshoots the recording
    measures what exists. Input to the MLX hallucination-on-silence gate (F12).
    Raises ``wave.Error``/``OSError`` on unreadable files; callers decide the
    failure policy (the finalize gate fails open).
    """
    with wave.open(str(path), "rb") as w:
        sampwidth = w.getsampwidth()
        nframes = w.getnframes()
        framerate = w.getframerate()
        if nframes == 0 or sampwidth not in (1, 2, 4) or framerate <= 0:
            return float("-inf")
        start_frame = min(nframes, max(0, int(start_seconds * framerate)))
        end_frame = min(nframes, max(0, int(end_seconds * framerate)))
        if end_frame <= start_frame:
            return float("-inf")
        w.setpos(start_frame)
        frames = w.readframes(end_frame - start_frame)

    return _rms_dbfs_from_frames(frames, sampwidth)


def _rms_dbfs_from_frames(frames: bytes, sampwidth: int) -> float:
    normalized: list[float]
    if sampwidth == 2:
        ints = struct.unpack(f"<{len(frames) // 2}h", frames)
        normalized = [x / 32768.0 for x in ints]
    elif sampwidth == 1:
        # unsigned 8-bit
        normalized = [(x - 128) / 128.0 for x in frames]
    else:
        # 32-bit float — rare for our pipeline; best-effort
        normalized = list(struct.unpack(f"<{len(frames) // 4}f", frames))

    if not normalized:
        return float("-inf")
    mean_square = sum(x * x for x in normalized) / len(normalized)
    if mean_square <= 0.0:
        return float("-inf")
    return min(0.0, 10.0 * math.log10(mean_square))
