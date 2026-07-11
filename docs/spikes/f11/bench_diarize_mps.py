"""F11 spike (non-shipping): pyannote 4.x (speaker-diarization-community-1, the production model
via whisperx.diarize) — CPU vs MPS on the same audio. Verifies the 3.x-era MPS correctness bugs
(single-speaker collapse, aten::_fft_r2c fallback) and measures the speedup.

Usage: HF_TOKEN=... .venv/bin/python bench_diarize_mps.py <wav> <out.json>
Audio is preloaded in memory (torchcodec decoding is broken in this venv; production whisperx
also passes an in-memory waveform dict).
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
from typing import Any

import numpy as np


def load_waveform(path: str) -> dict[str, Any]:
    import torch

    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        sr = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    x = torch.from_numpy(pcm.astype(np.float32) / 32768.0)[None, :]
    return {"waveform": x, "sample_rate": sr}


def run(pipeline: Any, device: str, audio: dict[str, Any]) -> dict[str, Any]:
    import torch

    pipeline.to(torch.device(device))
    t0 = time.perf_counter()
    output = pipeline(audio)
    t = time.perf_counter() - t0
    ann = getattr(output, "speaker_diarization", output)
    turns = [
        {"start": round(seg.start, 3), "end": round(seg.end, 3), "speaker": label}
        for seg, _, label in ann.itertracks(yield_label=True)
    ]
    per_speaker: dict[str, float] = {}
    for turn in turns:
        per_speaker[turn["speaker"]] = per_speaker.get(turn["speaker"], 0.0) + (
            turn["end"] - turn["start"]
        )
    return {
        "device": device,
        "t_s": round(t, 2),
        "n_turns": len(turns),
        "n_speakers": len(per_speaker),
        "speech_s_per_speaker": {k: round(v, 1) for k, v in sorted(per_speaker.items())},
        "turns": turns,
    }


def frame_agreement(
    a: list[dict[str, Any]], b: list[dict[str, Any]], end_s: float, step: float = 0.01
) -> dict[str, Any]:
    """Frame-level agreement between two diarizations after greedy label mapping."""
    n = int(end_s / step)

    def labels(turns: list[dict[str, Any]]) -> list[str | None]:
        grid: list[str | None] = [None] * n
        for t in turns:
            for i in range(max(0, int(t["start"] / step)), min(n, int(t["end"] / step))):
                grid[i] = t["speaker"]
        return grid

    la, lb = labels(a), labels(b)
    pairs: dict[tuple[str, str], int] = {}
    for x, y in zip(la, lb, strict=True):
        if x is not None and y is not None:
            pairs[(x, y)] = pairs.get((x, y), 0) + 1
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for (x2, y2), _ in sorted(pairs.items(), key=lambda kv: -kv[1]):
        if x2 not in mapping and y2 not in used:
            mapping[x2] = y2
            used.add(y2)
    both = agree = speech_union = 0
    for x, y in zip(la, lb, strict=True):
        if x is None and y is None:
            continue
        speech_union += 1
        if x is not None and y is not None:
            both += 1
            if mapping.get(x) == y:
                agree += 1
    return {
        "label_mapping_a_to_b": mapping,
        "frames_speech_union": speech_union,
        "frames_both_speech": both,
        "agree_pct_of_both": round(100.0 * agree / both, 1) if both else None,
        "agree_pct_of_union": round(100.0 * agree / speech_union, 1) if speech_union else None,
    }


def main() -> None:
    wav, out_path = sys.argv[1], sys.argv[2]
    token = os.environ["HF_TOKEN"]

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=token)

    audio = load_waveform(wav)
    end_s = audio["waveform"].shape[1] / audio["sample_rate"]

    results: dict[str, Any] = {"mps_fallback_env": os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")}
    results["cpu"] = run(pipeline, "cpu", load_waveform(wav))
    try:
        results["mps"] = run(pipeline, "mps", load_waveform(wav))
    except Exception as e:
        results["mps"] = {"error": f"{type(e).__name__}: {e}"}

    if "error" not in results["mps"]:
        results["agreement_cpu_vs_mps"] = frame_agreement(
            results["cpu"]["turns"], results["mps"]["turns"], end_s
        )
        results["speedup_mps_over_cpu"] = round(results["cpu"]["t_s"] / results["mps"]["t_s"], 2)

    with open(out_path, "w") as f:
        json.dump(results, f, indent=1)
    slim = {
        k: ({kk: vv for kk, vv in v.items() if kk != "turns"} if isinstance(v, dict) else v)
        for k, v in results.items()
    }
    print(json.dumps(slim, indent=1))


if __name__ == "__main__":
    main()
