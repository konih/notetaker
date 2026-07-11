# F11 spike — Apple-Silicon GPU acceleration: benchmark + verification + decision

**Date:** 2026-07-11 · **Story:** F11 (feeds F12) · **Status:** done — decision below
**Machine:** Apple M5 Max, 36 GB unified memory, macOS 26.5.1 (Darwin 25.5), no CUDA
**Versions:** whisperx 3.8.5 · faster-whisper 1.2.1 · ctranslate2 4.7.1 · pyannote.audio 4.0.4 · torch 2.8.0 · mlx-whisper 0.4.3 · mlx 0.32.0 · Python 3.13

## Decision (TL;DR)

- **F12 (MLX transcription provider): GO.** mlx-whisper on the Apple GPU transcribes the same
  audio with the same model size (large-v3-turbo) **7.1× faster** than the production
  cpu/int8 path (measured here, not cited), with comparable transcript quality and word
  timestamps that reproduce the production speaker attribution at **97.7%** word-level agreement.
- **`WHISPERX_DIARIZE_DEVICE=mps` (the cheap half): GO — safe to use today.** pyannote 4.0.4
  (`speaker-diarization-community-1`, the exact model whisperx 3.8.5 loads) produces
  **identical speaker turns on MPS and CPU** (100% frame agreement, same turn count, same
  per-speaker seconds) and is **8× faster on 120 s, 20.5× on 600 s**, with **no** `PYTORCH_ENABLE_MPS_FALLBACK` needed.
  The 3.x-era single-speaker-collapse and `aten::_fft_r2c` bugs did **not** reproduce on
  4.0.4 + torch 2.8.

## Method

- **Audio:** real multi-speaker meeting speech — `tests/fixtures/wav/meeting_en_120s_16k_mono.wav`
  (AMI ES2002a headset mix, CC BY 4.0; 2 active speakers in this window) and a 600 s version made
  by concatenating that clip 5× (`ffmpeg -f concat`). Benchmarks ran on copies in scratch space;
  no operator data touched.
- **Baseline** mirrors `run_whisperx_finalize` defaults: whisperx `load_model("large-v3-turbo",
  "cpu", compute_type="int8")`, `transcribe(batch_size=8, language="en")`, plus the wav2vec2
  alignment step where noted. **MLX:** `mlx_whisper.transcribe(..., path_or_hf_repo=
  "mlx-community/whisper-large-v3-turbo", word_timestamps=True)`, run twice — cold (load +
  compile) and warm.
- MLX ran in an isolated env (`uv run --no-project --with mlx-whisper`); nothing was added to the
  project venv or `pyproject.toml`. Scripts: `docs/spikes/f11/` (spike-only, non-shipping).
- Sequential runs (no CPU/GPU contention between engines).

## 1. ASR benchmark — cpu/int8 (production) vs mlx-whisper (GPU), same model size

| Engine | Audio | Load | Transcribe | xRT | Peak RSS |
|---|---|---:|---:|---:|---:|
| whisperx / faster-whisper / CT2 **cpu int8**, batch 8 | 600 s | 5.7 s | **112.8 s** | 5.3× | 5.3 GB |
| **mlx-whisper** (Metal GPU), word_timestamps=True | 600 s | — | **15.8 s** warm (20.3 s cold incl. load+compile) | **37.9×** | 1.8 GB¹ |
| whisperx cpu int8 + wav2vec2 align (cpu) | 120 s | 6.8 s | 21.5 s + 1.9 s align | 5.6× | 3.7 GB |
| mlx-whisper | 120 s | — | 5.8 s warm (6.8 s cold) | 20.6× | 1.9 GB¹ |

**Speedup on this machine: 7.1× warm / 5.5× including cold start** (600 s audio) — better than
the cited M4 figure (~6.8×). On short clips the fixed overhead bites (3.7× on 120 s): the win
grows with session length, which is exactly the finalize workload. A 1-hour meeting extrapolates
to ~11 min (cpu) vs ~1.6 min (mlx) for the ASR step. Combined with §2, a 1-hour meeting's
finalize compute drops from ~38 min (CPU ASR + CPU diarization) to **~3 min** (MLX + MPS).

¹ `ru_maxrss` of the Python process; MLX Metal buffer wiring may not be fully visible in RSS.
Even so, 36 GB unified memory is far from stressed (OQ-F11-1): ASR and diarization also run
sequentially in finalize, and the diarization model is small.

**Quality (eyeball, same 120 s):** transcripts agree nearly verbatim on all matched content; MLX
segments finer and catches short backchannels the batched-VAD baseline drops ("Yeah.",
"Marketing."). One classic Whisper hallucination on a ~30 s low-speech stretch ("Thank you." at
39–42 s) that the baseline's external VAD suppresses — F12 should note this (silence gating /
`condition_on_previous_text` handling), it is inherent to VAD-less Whisper decoding.

## 2. pyannote 4.x on MPS — correctness + speed (the cheap sub-win)

Model: `pyannote/speaker-diarization-community-1` — exactly what production loads via
`whisperx.diarize.DiarizationPipeline`. Run **without** `PYTORCH_ENABLE_MPS_FALLBACK`.

| Audio | CPU | MPS | Speedup | Output diff |
|---|---:|---:|---:|---|
| 120 s | 50.9 s | 6.3 s | **8.1×** | **identical**: 26 turns / 2 speakers on both; per-speaker speech 38.6 s + 50.6 s on both; 100% frame-level agreement (10 ms grid) |
| 600 s | 273.8 s | 13.4 s | **20.5×** | **identical**: 124 turns / 2 speakers on both; per-speaker speech 192.8 s + 253.1 s on both; 100% frame-level agreement |

- **No single-speaker collapse** (the pyannote 3.x MPS bug) — both devices found the same 2
  speakers in this window.
- **No MPS-unimplemented-op error** and no fallback env var needed: torch 2.8 covers the ops
  (`aten::_fft_r2c` era is over), so the speedup is real, not a silent CPU fallback.
- Diarization, not ASR, is the finalize hog on CPU: 273.8 s for 600 s of audio (≈ 0.46× RT — a
  1-hour meeting spends ~27 min diarizing on CPU vs ~1.3 min on MPS). The MPS win is material
  on its own, independent of F12, and larger than the ASR win in absolute minutes.
- Note: `WHISPERX_DIARIZE_DEVICE` already exists in config (`whisperx_diarize_device`); an
  operator can set `=mps` today. Follow-up candidate: make `_resolve_diarize_device` auto-prefer
  MPS on Apple Silicon (currently auto lands on CPU).

## 3. mlx-whisper word timestamps → speaker overlap-assignment (what F12 must build)

Compared per-word speaker assignment by interval-overlap against the **same** pyannote CPU turns:
whisperx wav2vec2-aligned words vs mlx-whisper words (120 s AMI clip).

| Metric | Value |
|---|---|
| words (whisperx-aligned / mlx) | 195 / 420 (mlx transcribes more of the overlapping/backchannel speech) |
| matched words (text-sequence match) | 171 |
| **same speaker assigned** | **97.7%** |
| word-start delta p50 / p90 / max | 0.096 s / 0.49 s / 4.1 s |

The handful of disagreements are dominated by **zero-duration mlx words** (start == end → no
overlap with any turn). F12's `assign_speakers_by_overlap` needs the obvious guards: pad or
midpoint-match zero/near-zero-duration words, and fall back to nearest turn. With that, MLX
timestamps (attention/DTW) are **sufficient for meeting speaker attribution**; they remain coarser
than wav2vec2 forced alignment (p90 ≈ 0.5 s), so frame-tight subtitle use would regress — accepted
per F11 research.

## Recommendation for F12 (shape)

1. **Finalize/offline first** (OQ-F11-2): the measured 7× is on exactly the finalize workload, and
   the offline path has the simpler contract. Implement behind the existing `OfflineTranscriber`
   port (A9) — factor the ASR step out of `run_whisperx_finalize` so MLX vs CTranslate2 is
   selectable; keep pyannote diarization (now defaulting/allowed on MPS per §2); add the pure
   `assign_speakers_by_overlap(words, turns)` (domain, unit-tested, with the zero-duration guard).
2. **Live provider second** — mlx xRT ≈ 38× on large-v3-turbo makes a keyless local live provider
   very attractive (a 5 s chunk in ~150 ms warm), but it's a separate surface; phase it.
3. Gating: optional macOS-arm64-only extra, `importorskip` in CI (no MLX in unit lane), clean
   `TranscriptionProviderError` when unavailable, `doctor` check. Model:
   `mlx-community/whisper-large-v3-turbo` (~1.6 GB, one-time download; F9's first-run-download
   precedent applies).
4. Non-goals confirmed: no CTranslate2-on-Metal miracle exists (faster-whisper #911 still the
   state of the world); do not adopt `sooth/whisperx-mlx` (experimental).

## Caveats / limits of this spike

- One machine (M5 Max), one meeting corpus window (AMI ES2002a, 2 active speakers, English), one
  model size. No WER scoring — eyeball + word-sequence matching only. The 600 s file is a 5×
  concat (content repetition is fine for throughput, meaningless for diarization DER).
- 4-speaker MPS behaviour not exercised (this window has 2); CPU/MPS equality is the claim, not
  absolute diarization quality.
- Peak-RSS numbers under-report Metal wired memory (footnote ¹).

## Reproduce

```bash
# baseline (project venv), 600 s concat copy of the AMI fixture
.venv/bin/python docs/spikes/f11/bench_asr_baseline.py <wav> out.json [--align]
# mlx (isolated env)
uv run --no-project --with mlx-whisper python docs/spikes/f11/bench_asr_mlx.py <wav> out.json
# pyannote CPU vs MPS (needs HF_TOKEN)
HF_TOKEN=... .venv/bin/python docs/spikes/f11/bench_diarize_mps.py <wav> out.json
# overlap-assignment comparison over the three JSONs
python3 docs/spikes/f11/compare_overlap_assignment.py baseline_120_align.json mlx_120.json diarize_120.json out.json
```
