from __future__ import annotations

import struct
import wave
from pathlib import Path


def test_peak_linear_s16le_silence(tmp_path: Path) -> None:
    path = tmp_path / "s.wav"
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<200h", *([0] * 200)))

    from live_meeting_transcriber.audio.wav_level import peak_linear_from_wav_path

    assert peak_linear_from_wav_path(path) == 0.0


def test_peak_linear_s16le_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "l.wav"
    samples = [0] * 50 + [20000] * 50
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    from live_meeting_transcriber.audio.wav_level import peak_linear_from_wav_path

    p = peak_linear_from_wav_path(path)
    assert 0.5 < p <= 1.0
