"""F11 spike (non-shipping): benchmark the production ASR path — WhisperX / faster-whisper /
CTranslate2 on cpu/int8 — mirroring run_whisperx_finalize's settings (large-v3-turbo, batch 8).

Usage: .venv/bin/python bench_asr_baseline.py <wav> <out.json> [--align]
"""

from __future__ import annotations

import gc
import json
import resource
import sys
import time


def main() -> None:
    wav, out_path = sys.argv[1], sys.argv[2]
    do_align = "--align" in sys.argv

    import whisperx

    audio = whisperx.load_audio(wav)
    audio_s = len(audio) / 16000.0

    t0 = time.perf_counter()
    model = whisperx.load_model("large-v3-turbo", "cpu", compute_type="int8", language="en")
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    result = model.transcribe(audio, batch_size=8, language="en")
    t_transcribe = time.perf_counter() - t0

    segments = result["segments"]
    del model
    gc.collect()

    t_align = None
    if do_align:
        t0 = time.perf_counter()
        model_a, metadata = whisperx.load_align_model(language_code="en", device="cpu")
        aligned = whisperx.align(
            segments, model_a, metadata, audio, "cpu", return_char_alignments=False
        )
        t_align = time.perf_counter() - t0
        result = aligned

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2)  # macOS: bytes
    out = {
        "engine": "whisperx/faster-whisper/ctranslate2 cpu int8 batch=8",
        "model": "large-v3-turbo",
        "audio_s": audio_s,
        "t_load_s": round(t_load, 2),
        "t_transcribe_s": round(t_transcribe, 2),
        "t_align_s": round(t_align, 2) if t_align is not None else None,
        "xrt_transcribe": round(audio_s / t_transcribe, 2),
        "peak_rss_mb": round(peak_rss_mb, 1),
        "n_segments": len(result["segments"]),
        "segments": [
            {
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")).strip(),
                "words": [
                    {"word": w.get("word"), "start": w.get("start"), "end": w.get("end")}
                    for w in s.get("words", [])
                ]
                if do_align
                else None,
            }
            for s in result["segments"]
        ],
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "segments"}, indent=1))


if __name__ == "__main__":
    main()
