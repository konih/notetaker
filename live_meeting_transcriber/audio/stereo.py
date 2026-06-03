"""Stereo helpers: RMS-balanced mono (meetings), per-channel extract, dual-channel energy stats."""

from __future__ import annotations

import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StereoPCM:
    mic: Any
    system: Any
    sample_rate: int


def read_stereo_pcm(path: Path) -> StereoPCM | None:
    """Load stereo int16 WAV as float32 mic (L) / system (R) arrays. Returns ``None`` if not stereo."""
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        with wave.open(str(path), "r") as wf:
            if wf.getnchannels() != 2 or wf.getsampwidth() != 2:
                return None
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except Exception:
        return None
    data = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
    left = data[:, 0].astype(np.float32)
    right = data[:, 1].astype(np.float32)
    return StereoPCM(mic=left, system=right, sample_rate=rate)


def rms_mixdown_to_mono_wav(stereo_path: Path, *, sample_rate_hz: int) -> Path:
    """Per-channel RMS normalization then average (meetscribe-style), write mono PCM WAV."""
    try:
        import numpy as np
    except ImportError:
        return _ffmpeg_average_mono(stereo_path, sample_rate_hz=sample_rate_hz)

    try:
        with wave.open(str(stereo_path), "r") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except Exception:
        return _ffmpeg_average_mono(stereo_path, sample_rate_hz=sample_rate_hz)

    if n_channels != 2 or sampwidth != 2:
        return _ffmpeg_average_mono(stereo_path, sample_rate_hz=sample_rate_hz)

    data = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)
    left = data[:, 0].astype(np.float32)
    right = data[:, 1].astype(np.float32)

    silence_thr = 50.0
    left_active = left[np.abs(left) > silence_thr]
    right_active = right[np.abs(right) > silence_thr]
    left_rms = float(np.sqrt(np.mean(left_active**2))) if len(left_active) > 0 else 0.0
    right_rms = float(np.sqrt(np.mean(right_active**2))) if len(right_active) > 0 else 0.0

    if left_rms > 0 and right_rms > 0:
        target_rms = max(left_rms, right_rms)
        left_scaled = left * (target_rms / left_rms)
        right_scaled = right * (target_rms / right_rms)
        mono = (left_scaled + right_scaled) * 0.5
    elif right_rms > 0:
        mono = right
    elif left_rms > 0:
        mono = left
    else:
        mono = (left + right) * 0.5

    mono = np.clip(mono, -32768, 32767).astype(np.int16)
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    with wave.open(str(tmp), "w") as wf_out:
        wf_out.setnchannels(1)
        wf_out.setsampwidth(2)
        wf_out.setframerate(framerate)
        wf_out.writeframes(mono.tobytes())
    return tmp


def _ffmpeg_average_mono(stereo_path: Path, *, sample_rate_hz: int) -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(stereo_path),
        "-filter_complex",
        "[0:a]pan=mono|c0=0.5*c0+0.5*c1[out]",
        "-map",
        "[out]",
        "-ar",
        str(sample_rate_hz),
        "-acodec",
        "pcm_s16le",
        str(tmp),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return tmp


def extract_mono_channel_wav(stereo_path: Path, channel: int, *, sample_rate_hz: int) -> Path:
    """Extract one channel (0 = left/mic, 1 = right/system) to mono WAV via ffmpeg."""
    if channel not in (0, 1):
        raise ValueError("channel must be 0 or 1")
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(stereo_path),
        "-filter_complex",
        f"[0:a]pan=mono|c0=c{channel}[out]",
        "-map",
        "[out]",
        "-ar",
        str(sample_rate_hz),
        "-acodec",
        "pcm_s16le",
        str(tmp),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return tmp


@dataclass(frozen=True)
class LabeledSpan:
    start: float
    end: float
    speaker: str


def compute_speaker_mic_ratios(
    stereo: StereoPCM,
    segments: list[LabeledSpan],
) -> dict[str, float]:
    """For each speaker id, fraction of energy on mic (L) vs mic+system for their intervals."""
    try:
        import numpy as np
    except ImportError:
        return {}

    sr = stereo.sample_rate
    n = len(stereo.mic)
    ratios: dict[str, list[float]] = {}

    for seg in segments:
        start = max(0, min(int(seg.start * sr), n))
        end = max(0, min(int(seg.end * sr), n))
        if end <= start:
            continue
        mic_rms = float(np.sqrt(np.mean(stereo.mic[start:end] ** 2)))
        sys_rms = float(np.sqrt(np.mean(stereo.system[start:end] ** 2)))
        denom = mic_rms + sys_rms
        ratio = mic_rms / denom if denom > 1e-8 else 0.5
        ratios.setdefault(seg.speaker, []).append(ratio)

    out: dict[str, float] = {}
    for spk, vals in ratios.items():
        out[spk] = float(sum(vals) / len(vals)) if vals else 0.5
    return out


def you_remote_for_audio_interval(stereo: StereoPCM, t0_sec: float, t1_sec: float) -> str:
    """Return YOU if left/mic RMS dominates the interval, else REMOTE."""
    try:
        import numpy as np
    except ImportError:
        return "unknown"
    sr = stereo.sample_rate
    n = len(stereo.mic)
    start = max(0, min(int(t0_sec * sr), n))
    end = max(0, min(int(t1_sec * sr), n))
    if end <= start:
        return "unknown"
    mic_rms = float(np.sqrt(np.mean(stereo.mic[start:end] ** 2)))
    sys_rms = float(np.sqrt(np.mean(stereo.system[start:end] ** 2)))
    if mic_rms + sys_rms < 1e-8:
        return "unknown"
    return "YOU" if mic_rms >= sys_rms else "REMOTE"


def map_pyannote_to_you_remote(speaker_mic_ratio: dict[str, float]) -> dict[str, str]:
    """Map SPEAKER_xx cluster ids to YOU / REMOTE / REMOTE_n (meetscribe-style heuristics)."""
    if not speaker_mic_ratio:
        return {}

    you_speaker = max(speaker_mic_ratio, key=lambda s: speaker_mic_ratio[s])
    you_ratio = speaker_mic_ratio[you_speaker]
    other_ratios = [r for s, r in speaker_mic_ratio.items() if s != you_speaker]
    avg_other = sum(other_ratios) / len(other_ratios) if other_ratios else 0.0
    margin = you_ratio - avg_other

    label_map: dict[str, str] = {}
    if you_ratio > 0.5 or (margin > 0.1 and you_ratio > 0.15):
        label_map[you_speaker] = "YOU"
        remote_speakers = [s for s in sorted(speaker_mic_ratio) if s != you_speaker]
        if len(remote_speakers) == 1:
            label_map[remote_speakers[0]] = "REMOTE"
        else:
            for i, spk in enumerate(remote_speakers):
                label_map[spk] = f"REMOTE_{i + 1}"
    else:
        all_speakers = sorted(speaker_mic_ratio)
        if len(all_speakers) == 1:
            label_map[all_speakers[0]] = "REMOTE"
        else:
            for i, spk in enumerate(all_speakers):
                label_map[spk] = f"REMOTE_{i + 1}"
    return label_map
