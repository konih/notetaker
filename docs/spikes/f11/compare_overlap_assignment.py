"""F11 spike (non-shipping): would mlx-whisper word timestamps + pyannote turns give the same
speaker attribution as the production WhisperX path (wav2vec2 forced alignment +
whisperx.assign_word_speakers)?

Takes the JSON outputs of the other three scripts and compares, per word, the speaker that
interval-overlap assignment picks from (a) whisperx-aligned words vs (b) mlx words, against the
same pyannote CPU turns. Reports word-level agreement and timestamp deltas for matched words.

Usage: python compare_overlap_assignment.py <baseline_align.json> <mlx.json> <diarize.json> <out.json>
"""

from __future__ import annotations

import json
import sys
from typing import Any


def flat_words(doc: dict[str, Any]) -> list[dict[str, Any]]:
    words = []
    for seg in doc["segments"]:
        for w in seg.get("words") or []:
            if w.get("start") is None or w.get("end") is None:
                continue
            words.append(
                {
                    "word": str(w["word"]).strip().lower(),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
            )
    return words


def assign(word: dict[str, Any], turns: list[dict[str, Any]]) -> str | None:
    best, best_ov = None, 0.0
    for t in turns:
        ov = min(word["end"], t["end"]) - max(word["start"], t["start"])
        if ov > best_ov:
            best, best_ov = t["speaker"], ov
    return best


def load(path: str) -> dict[str, Any]:
    with open(path) as f:
        data: dict[str, Any] = json.load(f)
    return data


def main() -> None:
    base_p, mlx_p, dia_p, out_p = sys.argv[1:5]
    base, mlx, dia = load(base_p), load(mlx_p), load(dia_p)
    turns = dia["cpu"]["turns"]

    wb, wm = flat_words(base), flat_words(mlx)

    # Greedy sequence match on normalized word text within a sliding window.
    matches = []
    j = 0
    for b in wb:
        for k in range(j, min(j + 8, len(wm))):
            if (
                wm[k]["word"].strip(".,!?;:'\"").casefold()
                == b["word"].strip(".,!?;:'\"").casefold()
            ):
                matches.append((b, wm[k]))
                j = k + 1
                break

    n = agree = 0
    deltas = []
    disagreements: list[dict[str, Any]] = []
    for b, m in matches:
        sb, sm = assign(b, turns), assign(m, turns)
        deltas.append(abs(b["start"] - m["start"]))
        if sb is None and sm is None:
            continue
        n += 1
        if sb == sm:
            agree += 1
        elif len(disagreements) < 20:
            disagreements.append(
                {
                    "word": b["word"],
                    "wx": [b["start"], b["end"], sb],
                    "mlx": [m["start"], m["end"], sm],
                }
            )

    deltas.sort()
    out = {
        "n_words_whisperx": len(wb),
        "n_words_mlx": len(wm),
        "n_matched": len(matches),
        "n_assigned": n,
        "speaker_agreement_pct": round(100.0 * agree / n, 1) if n else None,
        "start_delta_s_p50": round(deltas[len(deltas) // 2], 3) if deltas else None,
        "start_delta_s_p90": round(deltas[int(len(deltas) * 0.9)], 3) if deltas else None,
        "start_delta_s_max": round(deltas[-1], 3) if deltas else None,
        "sample_disagreements": disagreements,
    }
    with open(out_p, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
