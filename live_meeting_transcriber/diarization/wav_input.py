"""Load PCM WAV files for pyannote when torchcodec/ffmpeg decoding is unavailable."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any


def load_pyannote_audio_input(path: Path) -> dict[str, Any]:
    """Return ``{'waveform': Tensor, 'sample_rate': int}`` for pyannote Pipeline input."""
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("torch is required for pyannote diarization") from e

    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        if sample_width != 2:
            msg = f"Unsupported WAV sample width: {sample_width} bytes (expected 16-bit PCM)"
            raise ValueError(msg)
        frames = wav.readframes(wav.getnframes())

    import numpy as np

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 1:
        tensor = torch.from_numpy(samples).unsqueeze(0)
    else:
        tensor = torch.from_numpy(samples.reshape(-1, channels).T)
    return {"waveform": tensor, "sample_rate": sample_rate}
