"""F11 spike (non-shipping): benchmark mlx-whisper (Apple-Silicon GPU via MLX) on the same audio
and model size as the production baseline (whisper large-v3-turbo), word timestamps ON.

Usage: uv run --no-project --with mlx-whisper python bench_asr_mlx.py <wav> <out.json>
"""

from __future__ import annotations

import json
import resource
import sys
import time

MODEL = "mlx-community/whisper-large-v3-turbo"


def main() -> None:
    wav, out_path = sys.argv[1], sys.argv[2]

    import mlx_whisper

    # Pass 1 includes model download/load + MLX graph compile; pass 2 is the warm number.
    t0 = time.perf_counter()
    result = mlx_whisper.transcribe(wav, path_or_hf_repo=MODEL, word_timestamps=True, language="en")
    t_cold = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = mlx_whisper.transcribe(wav, path_or_hf_repo=MODEL, word_timestamps=True, language="en")
    t_warm = time.perf_counter() - t0

    segments = result["segments"]
    audio_s = max(float(s["end"]) for s in segments) if segments else 0.0
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2)  # macOS: bytes

    out = {
        "engine": "mlx-whisper (Metal GPU)",
        "model": MODEL,
        "audio_s_last_segment_end": audio_s,
        "t_cold_s": round(t_cold, 2),
        "t_warm_s": round(t_warm, 2),
        "xrt_warm_vs_last_end": round(audio_s / t_warm, 2) if t_warm else None,
        "peak_rss_mb": round(peak_rss_mb, 1),
        "n_segments": len(segments),
        "segments": [
            {
                "start": float(s["start"]),
                "end": float(s["end"]),
                "text": str(s["text"]).strip(),
                "words": [
                    {"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
                    for w in s.get("words", [])
                ],
            }
            for s in segments
        ],
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "segments"}, indent=1))


if __name__ == "__main__":
    main()
