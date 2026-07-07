from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest
from live_meeting_transcriber.diarization.wav_input import load_pyannote_audio_input


def _write_mono_wav(path: Path, *, samples: list[int], sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        frames = b"".join(struct.pack("<h", s) for s in samples)
        wav.writeframes(frames)


def test_load_pyannote_audio_input_mono(tmp_path: Path) -> None:
    wav_path = tmp_path / "mono.wav"
    _write_mono_wav(wav_path, samples=[0, 1000, -1000, 0])
    payload = load_pyannote_audio_input(wav_path)
    assert payload["sample_rate"] == 16000
    assert payload["waveform"].shape == (1, 4)


def test_load_pyannote_audio_input_requires_torch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object):
        if name == "torch":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    wav_path = tmp_path / "mono.wav"
    _write_mono_wav(wav_path, samples=[0, 0])
    with pytest.raises(RuntimeError, match="torch is required"):
        load_pyannote_audio_input(wav_path)
