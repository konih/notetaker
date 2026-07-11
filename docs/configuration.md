## Configuration

Configuration is loaded via `pydantic-settings`. The **YAML config file is the source of
truth** (U21); environment variables and `.env` files are still honoured for back-compat.

### Config file (`config.yaml`) — the source of truth

Settings live in a single human-readable YAML file at
`$XDG_CONFIG_HOME/live-meeting-transcriber/config.yaml` (default:
`~/.config/live-meeting-transcriber/config.yaml`; on macOS see
[Where files live](#where-files-live-per-platform)). Editing settings **in-app** (Settings
screen → `e: edit`) writes this file atomically. Two groups are editable in-app:

- **Runtime toggles** (U15) — a deliberately small, safe subset (note: a field set via an env var still wins over the saved `config.yaml` value on next launch — env > yaml precedence):
  `FINALIZE_ON_SESSION_STOP`, `AUDIO_SILENCE_SKIP_ENABLED` and `KEEP_AUDIO_CHUNKS` as
  switches, plus `AUDIO_SILENCE_THRESHOLD_DBFS` and `AUDIO_CHUNK_SECONDS` as validated
  number inputs. Out-of-range or non-numeric values show an inline error and **nothing is
  saved** until fixed (the same limits as the model: threshold `-120..0`, chunk `1..300`).
- **Folders & files** (U21) — path fields (log file, Obsidian
  people/meetings/template/screenshots dirs, screenshots source) set through a
  **folder/file picker** so you never hand-edit a path.

All in-app edits apply on **restart** — the running session keeps the configuration it
started with — but the read-only Settings screen shows the saved values immediately.
Everything else (providers, models, devices, video tuning, …) remains env/`config.yaml`/
`.env`-only; there is intentionally no full in-app settings editor.

The file is regenerated on each save — user-added comments are **not** preserved — and a
header banner documents this. Secrets (`OPENAI_API_KEY`, `HF_TOKEN`) are intentionally
**never** written to `config.yaml`; keep them in an environment variable or `.env`.

### Precedence

Sources are resolved highest-priority first:

1. **Environment variable** (e.g. `TRANSCRIPTION_MODEL=…`)
2. **`config.yaml`** (the in-app store)
3. **`.env` file** (back-compat / fallback)
4. Built-in default

> **Note:** the first in-app save writes the *full* resolved settings into `config.yaml`,
> which sits **above** `.env`. After that first save, editing a value in `.env` has no
> effect for any field already in `config.yaml` — change it in-app (or in `config.yaml` /
> via an environment variable) instead.

### `.env` file locations (fallback)

`.env` files are read in order; **later files override earlier ones**:

1. `.env` in the app config directory (default `~/.config/live-meeting-transcriber/.env`; `$XDG_CONFIG_HOME` wins when set; macOS: see below)
2. `./.env` in the current working directory

Only existing files are loaded. See [`install-desktop.md`](install-desktop.md) for first-run setup when using the desktop launcher.

### Where files live (per platform)

Run **`live-transcriber paths`** to print the resolved locations on your machine
(`--config-dir` prints just the config directory, for scripts).

| | Linux (XDG) | macOS — fresh install (F5) |
|---|---|---|
| Config (`config.yaml`, `.env`, device prefs) | `~/.config/live-meeting-transcriber/` | `~/Library/Application Support/live-meeting-transcriber/` |
| Data (SQLite DB, logs, chunk audio) | `~/.local/share/live-meeting-transcriber/` | `~/Library/Application Support/live-meeting-transcriber/` |

Rules, in order:

1. An explicit `$XDG_CONFIG_HOME` always wins for the config directory (any platform).
2. On macOS, an **existing** legacy XDG directory keeps winning — installs made before
   the `~/Library` default keep their config and data exactly where they are; nothing is
   migrated or stranded. Only fresh installs (no legacy directory) use
   `~/Library/Application Support`.
3. `DATABASE_URL` and `LOG_FILE` still override the data-dir defaults individually.

### Environment variables

- `OPENAI_API_KEY`: required when `TRANSCRIPTION_PROVIDER=openai` or `LLM_PROVIDER=openai` (summaries still use OpenAI by default, so the key is usually required even with local transcription)
- `TRANSCRIPTION_PROVIDER`: `openai` (default) or `faster_whisper` (local; install `uv sync --extra faster-whisper`)
- `LLM_PROVIDER`: `openai` (default)
- `TRANSCRIPTION_MODEL`: default `gpt-4o-mini-transcribe` (OpenAI only)
- `FASTER_WHISPER_MODEL`: Whisper checkpoint size or path (default `small`) — `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3`, etc.
- `FASTER_WHISPER_DEVICE`: `auto` (default), `cpu`, or `cuda`
- `FASTER_WHISPER_COMPUTE_TYPE`: `default` (default), or e.g. `int8`, `float16` (see faster-whisper docs)
- `FASTER_WHISPER_LANGUAGE`: optional ISO code (e.g. `en`); leave empty for auto-detect
- `SUMMARY_MODEL`: default `gpt-4o-mini`
- `DATABASE_URL`: default `sqlite:////home/you/.local/share/live-meeting-transcriber/app.db`
- `AUDIO_CHUNK_SECONDS`: default `10`
- `AUDIO_SAMPLE_RATE`: default `16000`
- `AUDIO_CHANNELS`: default `1`
- `AUDIO_STEREO_MODE`: default `mixdown`. With `AUDIO_CHANNELS=2`, `mixdown` blends mic + system into one mono track for live ASR; `dual_path` transcribes mic (L) and system (R) **separately** to get channel-based speaker keys during capture.
  - `dual_path` requires **both** `AUDIO_CHANNELS=2` **and** `TRANSCRIPTION_PROVIDER=faster_whisper` (the OpenAI provider has no per-channel path). If either is missing, `dual_path` is silently inert and audio is mixed to mono — `live-transcriber record` and the TUI now print a one-line warning at startup when this happens.
- `AUDIO_SILENCE_SKIP_ENABLED`: default `true` — skip **live transcription** of chunks whose RMS level falls below `AUDIO_SILENCE_THRESHOLD_DBFS` (F1). Saves OpenAI tokens / faster-whisper compute on quiet stretches. The chunk's audio is **still appended to `full_session.wav` first**, so offline `finalize` / Speaker ID always work on the complete session audio; skipped chunks follow the normal `KEEP_AUDIO_CHUNKS` cleanup policy and are logged (`silent_chunk_skipped`, with RMS and a running count).
- `AUDIO_SILENCE_THRESHOLD_DBFS`: default `-70.0` (range `-120..0`) — RMS threshold in dBFS below which a chunk counts as silence. The default is deliberately far below quiet speech (~`-40` dBFS) and typical mic noise floors, so with default settings only true digital near-silence (e.g. a monitor source with nothing playing) is skipped. Raise it (e.g. `-55`) to skip more aggressively; set `AUDIO_SILENCE_SKIP_ENABLED=false` to always transcribe everything.
- `AUDIO_INCLUDE_MICROPHONE`: default `true` — mix **default monitor** (system/meeting playback) with **default microphone** (your voice) via ffmpeg `amix`
- `AUDIO_MICROPHONE_SOURCE`: optional explicit PulseAudio source name for the mic leg (see `live-transcriber devices`, marked with `^`)
- `AUDIO_MACOS_SYSTEM_CAPTURE`: macOS only, default `auto`. Controls how system/output audio is captured:
  - `auto` — use the driver-free **Core Audio process tap** on macOS 14.4+ (no BlackHole needed); fall back to an avfoundation loopback device on older macOS.
  - `coreaudio_tap` — always use the native tap (requires macOS 14.4+).
  - `avfoundation` — always use a BlackHole/Loopback device (the pre-F7 behaviour).

  The native tap uses a tiny bundled Swift helper compiled on first use (needs the Xcode command line tools) and, on first capture, triggers the **"System Audio Recording Only"** permission prompt — approve it once. See **[system-audio-capture.md](system-audio-capture.md)**.

> **Capturing Teams/Zoom/Meet audio (both sides of a call):** the default captures only
> your microphone. On **macOS 14.4+** the native Core Audio tap (default `AUDIO_MACOS_SYSTEM_CAPTURE=auto`)
> captures remote participants with **no extra software** — just approve the one-time system-audio
> prompt. On older macOS or when forced to `avfoundation`, add a loopback source (BlackHole);
> on Linux use a PipeWire/PulseAudio `.monitor`. See
> **[system-audio-capture.md](system-audio-capture.md)** for the full setup and the
> two-channel `dual_path` command.
- `LOG_LEVEL`: default `INFO`; use `DEBUG` for verbose recorder/offline finalize steps (also sets UI action dispatch to DEBUG). Put this in **project `.env`** if your IDE/shell does not load `.envrc` before `live-transcriber` starts.
- `LOG_ENABLE_FILE`: default `true` — append structured JSON lines to a rotating log file
- `LOG_FILE`: optional absolute path; default is under the app data directory (`…/logs/live-meeting-transcriber.log`)
- `LOG_FILE_MAX_MB`: rotation size per file (default `10`)
- `LOG_FILE_BACKUP_COUNT`: number of rotated backups to keep (default `5`)
- `KEEP_AUDIO_CHUNKS`: default `0`
- `SCREENSHOTS_EXPORT_ENABLED`: default `true` — embed matching screenshots in markdown exports
- `SCREENSHOTS_SOURCE_DIR`: optional; default `~/Pictures/Screenshots` (GNOME filenames `Screenshot from YYYY-MM-DD HH-MM-SS.png`)
- `LIVE_SCREEN_CAPTURE_ENABLED`: default `false` — **privacy: off unless you opt in.** When `true`, `record` (CLI and TUI) periodically captures the whole screen into `sessions/<id>/screenshots/` so you can later see who was speaking; captures are interleaved into markdown exports like slides/screenshots. macOS only (uses the `screencapture` CLI); requires the **Screen Recording** permission (System Settings → Privacy & Security → Screen Recording) for your terminal — without the grant, captures may show only the desktop wallpaper. On Linux the feature degrades to a one-time warning.
- `LIVE_SCREEN_CAPTURE_INTERVAL_SECONDS`: default `60` (min 5, max 3600) — seconds between live screen captures.
- `OBSIDIAN_PEOPLE_DIR`: optional; folder of person notes used for attendee autocomplete and where new person notes are created (see `OBSIDIAN_PERSON_TEMPLATE`).
- `OBSIDIAN_MEETINGS_DIR`: optional; folder where exported meeting notes are written (also the anchor for the default `OBSIDIAN_SCREENSHOTS_DIR`).
- `OBSIDIAN_MEETING_TEMPLATE`: optional; path to a Markdown template applied when exporting a meeting note.
- `OBSIDIAN_PERSON_TEMPLATE`: optional; path to a Markdown template applied when a new person note is created in `OBSIDIAN_PEOPLE_DIR`.
- `OBSIDIAN_SCREENSHOTS_DIR`: optional; default `<parent of OBSIDIAN_MEETINGS_DIR>/Images/Screenshots`
- `DIARIZATION_ENABLED` / `DIARIZATION_PROVIDER`: legacy flags (UI/settings); **live recording does not run pyannote per chunk**. Speaker attribution paths:
  - **Offline (recommended):** `live-transcriber finalize` — WhisperX ASR + pyannote on `full_session.wav` (needs `uv sync --extra whisperx`, `HF_TOKEN`, Python ≤ 3.13 for torch). Uses `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS` / `DIARIZATION_NUM_SPEAKERS` when diarization runs inside finalize.
  - **Live dual-channel:** `TRANSCRIPTION_PROVIDER=faster_whisper`, `AUDIO_CHANNELS=2`, `AUDIO_STEREO_MODE=dual_path` — transcribes mic (L) and system (R) separately with channel-based speaker keys (no pyannote during capture).
  - There is **no** `live-transcriber diarize` CLI (the unused per-chunk batch reprocessor was removed in A7); use `finalize` for offline speaker attribution.
- `HF_TOKEN`: Hugging Face token (required for pyannote in **finalize**). First **accept the licence for the model finalize actually pulls — [`pyannote/speaker-diarization-community-1`](https://hf.co/pyannote/speaker-diarization-community-1)** — while logged in as the token's account. Run **`live-transcriber doctor`** (or `task diarization:doctor`) to verify the token authenticates and the gated model is accessible before your first finalize.
- `PYANNOTE_MODEL`: default `pyannote/speaker-diarization-3.1`. **Note:** this only feeds the legacy `diarization` extra / live provider — the **finalize** path uses WhisperX's built-in `speaker-diarization-community-1` and ignores this setting.
- `DIARIZATION_NUM_SPEAKERS`: optional exact speaker count for pyannote during finalize.
- `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS`: optional bounds when `DIARIZATION_NUM_SPEAKERS` is unset. `MIN` must be ≤ `MAX`.

**Offline finalize (WhisperX)** — the `live-transcriber finalize` re-transcription + diarization pass over `full_session.wav` (needs `uv sync --extra whisperx`, `HF_TOKEN`, Python ≤ 3.13 for torch):

- `FINALIZE_ON_SESSION_STOP`: default `false`. When `true` (and `HF_TOKEN` is set), stopping a recording automatically enqueues the offline finalize pass; otherwise run `live-transcriber finalize` manually.
- `OFFLINE_ASR_ENGINE`: default `auto` — which engine runs the offline finalize transcription: `whisperx` (CTranslate2; the previous behaviour), `mlx` (mlx-whisper on the Apple GPU — Apple Silicon only, needs the `mlx` extra: `uv sync --extra mlx`), or `auto` (use MLX when the machine is Apple Silicon **and** the `mlx` extra is installed — installing the extra is the opt-in — else WhisperX). Explicit values win; an explicit `mlx` that cannot run on this machine logs a warning and falls back to the WhisperX path — finalize never fails over an engine preference. Measured ~7x faster than the cpu/int8 WhisperX path at equal model size on an M-series GPU (`docs/spikes/2026-07-11-f11-apple-silicon-asr.md`). On the MLX path, word-level speaker attribution uses interval-overlap against the pyannote turns (97.7% agreement with the WhisperX wav2vec2 alignment in the spike); timestamps are slightly coarser than wav2vec2 forced alignment.
- `MLX_WHISPER_MODEL`: default `mlx-community/whisper-large-v3-turbo` — Hugging Face repo of the MLX-converted Whisper checkpoint used when the MLX engine is active (~1.6 GB, downloaded on first use).
- `MLX_SILENCE_GATE_DBFS`: default `-60.0` (range `-120..0`) — hallucination-on-silence gate for the MLX engine. mlx-whisper lacks the external VAD suppression of the WhisperX baseline and can invent short phrases ("Thank you.") over quiet stretches; finalize drops any MLX segment whose audio window's RMS is strictly below this level. The default sits far below quiet speech (~`-40` dBFS) so real speech is never gated; unmeasurable windows keep the segment (fail open). Set `-120` to effectively disable. Residual risk: hallucinations over audible non-speech (music, keyboard noise) or over a low-level speech bed are not caught — on the very quiet F11 AMI fixture the hallucinated window measured ~`-49` dBFS vs ~`-46` for real speech (verified 2026-07-11: its `no_speech_prob` was 0.0, so Whisper's own gate misses it too), too close for a safe default; raise the gate per environment if your captures are loud enough to afford it.
- `WHISPERX_MODEL`: default `large-v3-turbo` — Whisper checkpoint used for the finalize re-transcription.
- `WHISPERX_DEVICE`: optional; compute device for the WhisperX ASR model — **`cpu` or `cuda` only** (WhisperX's ASR backend is CTranslate2, which has **no MPS/Metal backend**). Unset auto-selects `cuda` when available, otherwise `cpu`. On **Apple Silicon the ASR always runs on CPU** — an `mps` value (auto or explicit) is coerced to `cpu`, since CTranslate2 cannot use it.
- `WHISPERX_TORCH_DEVICE`: optional; overrides the torch device for alignment when it must differ from `WHISPERX_DEVICE`.
- `WHISPERX_COMPUTE_TYPE`: default `float16` — CTranslate2 compute type (e.g. `int8`, `float32`). `float16` has no efficient CPU path, so on CPU (incl. Apple Silicon) it is automatically downgraded to `int8`.
- `WHISPERX_BATCH_SIZE`: default `8` (1–64) — lower it (2–4) and/or pick a smaller `WHISPERX_MODEL` if transcription OOMs.
- `WHISPERX_LANGUAGE`: optional ISO code (e.g. `en`); leave empty for auto-detect.
- `WHISPERX_SKIP_ALIGNMENT`: default `false` — skip the word-alignment stage (faster, coarser timestamps).
- `WHISPERX_DIARIZE_DEVICE`: optional; device for the pyannote diarization model. Unset auto-selects: on **Apple Silicon with usable MPS it defaults to `mps`** (verified byte-identical to CPU and ~8-20x faster — see `docs/spikes/2026-07-11-f11-apple-silicon-asr.md`; if MPS errors at runtime, finalize logs a warning and retries once on CPU), and defaults to CPU when alignment uses CUDA (avoids a second GPU model OOMing). An explicit value always wins and never falls back: set `cpu` to opt out of MPS, or `cuda`/`cuda:0` to force GPU diarization if you have the VRAM.

Speaker CLI:

- `live-transcriber doctor` — check diarization prerequisites (extras, ffmpeg, HF token auth, gated-model licence, resolved device/compute) and print a fix for the first thing missing. Also `task diarization:doctor`.
- `live-transcriber speakers --session-id <uuid>` — transcript keys, stored diarization keys, aliases.
- `live-transcriber speaker-alias --session-id <uuid> --speaker speaker_1 --name "Konrad"` (also accepts `SPEAKER_00`-style labels; normalized to `speaker_*` keys).

Video import and slide detection (`live-transcriber transcribe-video`):

- `VIDEO_SLIDE_STRATEGY`: `frame_diff` (default) or `ffmpeg_scene` — override per run with `--strategy`
- `VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS`: seconds between frame samples (default `2.0`; used by `frame_diff` only)
- `VIDEO_SLIDE_CHANGE_THRESHOLD`: change sensitivity (default `0.12`; meaning depends on strategy — see matrix below)
- `VIDEO_SLIDE_MIN_INTERVAL_SECONDS`: minimum seconds between saved slide candidates (default `15.0`)
- `VIDEO_SLIDE_MAX_CANDIDATES`: cap on detected candidates (default `120`)

**Slide detection strategy matrix**

| Strategy | Mechanism | `VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS` | `VIDEO_SLIDE_CHANGE_THRESHOLD` |
|----------|-----------|--------------------------------------|--------------------------------|
| `frame_diff` (default) | Sample grayscale frames every N seconds; flag when mean absolute pixel diff / 255 exceeds threshold | **Used** — sampling cadence | Pixel diff ratio (0.01–1.0); lower = more sensitive |
| `ffmpeg_scene` | ffmpeg `select='gt(scene,THRESH)'` scene-cut filter; then apply min interval + max cap | **Ignored** — ffmpeg finds cuts | ffmpeg scene score (0.01–1.0); lower = more cuts |

Shared params (`VIDEO_SLIDE_MIN_INTERVAL_SECONDS`, `VIDEO_SLIDE_MAX_CANDIDATES`) apply to both strategies. CLI flags `--sample-interval`, `--threshold`, `--min-interval`, and `--max-candidates` override env defaults for a single run.

**Preview workflow** (tune detection without re-transcribing):

1. Import: `live-transcriber transcribe-video --source <path-or-url>` (creates session + transcript; stores source video under app data).
2. Preview only on import: add `--preview-only` — transcribes and runs detection, prints candidate timestamps/scores, does **not** save slides.
3. Re-preview existing session: `live-transcriber slides preview --session-id <uuid> [--strategy …] [--sample-interval …] [--threshold …] [--min-interval …] [--max-candidates …]` — writes thumbnail previews under `imports/slide_previews/<session-id>/` and lists paths.
4. Apply after review: `live-transcriber slides apply --session-id <uuid> [--yes-slides]` — re-runs detection, optional y/n/a/q prompts (`slide_review.py`), saves PNGs + `sessions/<id>/slides/slides.json`.

On `transcribe-video` without `--preview-only`, slide extraction runs inline (same flags as above). Use `--no-slides` to skip slides entirely; `--yes-slides` to accept all candidates without prompts.

**Cleanup** (`live-transcriber cleanup`) — destructive; **dry-run by default** (lists paths only). Pass `--yes` or `--no-dry-run` to delete.

| Flag | Effect |
|------|--------|
| `--session-id <uuid>` | Purge one session's artifacts (repeatable): `chunks/`, `sessions/` (audio, slides, source video), `imports/slide_previews/`, `exports/screenshots/<id>/`, matching `exports/<id>_*.md` |
| `--all-sessions` | Same purge for every session row in the database |
| `--orphans` | Remove chunk/session/preview/export dirs whose UUID folder has no DB row |
| `--imports-cache` | Clear `imports/downloads/` (yt-dlp cache) |
| `--logs` | Remove files under `logs/` |
| `--exports` | Remove all files under `exports/` |

At least one target flag is required. Example: `live-transcriber cleanup --orphans` then `live-transcriber cleanup --orphans --yes`.

### Notes

- **Live vs offline speakers:** During `record`, chunks are transcribed as-is (mono mixdown or `dual_path` stereo with faster-whisper). Cluster labels (`speaker_1`, …) from pyannote appear after **`finalize`**, not on every live chunk when `DIARIZATION_ENABLED=true`.
- **Debug: only `speaker_1` after finalize** — Often mixed mono or too few speakers hinted; try `DIARIZATION_NUM_SPEAKERS=2`, `dual_path` capture, or longer sessions before finalize.
- Never commit real API keys or `HF_TOKEN`.
- By default, transcript text is not logged (privacy).
- Offline diarization runs **locally** (pyannote via WhisperX); it does not send audio to OpenAI.
