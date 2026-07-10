## Configuration

Configuration is loaded via `pydantic-settings`. The **YAML config file is the source of
truth** (U21); environment variables and `.env` files are still honoured for back-compat.

### Config file (`config.yaml`) — the source of truth

Settings live in a single human-readable YAML file at
`$XDG_CONFIG_HOME/live-meeting-transcriber/config.yaml` (default:
`~/.config/live-meeting-transcriber/config.yaml`). Editing settings **in-app** (Settings
screen → `e: edit`) writes this file atomically; path fields (log file, Obsidian
people/meetings/template/screenshots dirs, screenshots source) are set through a
**folder/file picker** so you never hand-edit a path. Path changes apply on restart.

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

1. `$XDG_CONFIG_HOME/live-meeting-transcriber/.env` (default: `~/.config/live-meeting-transcriber/.env`)
2. `./.env` in the current working directory

Only existing files are loaded. See [`install-desktop.md`](install-desktop.md) for first-run setup when using the desktop launcher.

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
- `OBSIDIAN_PEOPLE_DIR`: optional; folder of person notes used for attendee autocomplete and where new person notes are created (see `OBSIDIAN_PERSON_TEMPLATE`).
- `OBSIDIAN_MEETINGS_DIR`: optional; folder where exported meeting notes are written (also the anchor for the default `OBSIDIAN_SCREENSHOTS_DIR`).
- `OBSIDIAN_MEETING_TEMPLATE`: optional; path to a Markdown template applied when exporting a meeting note.
- `OBSIDIAN_PERSON_TEMPLATE`: optional; path to a Markdown template applied when a new person note is created in `OBSIDIAN_PEOPLE_DIR`.
- `OBSIDIAN_SCREENSHOTS_DIR`: optional; default `<parent of OBSIDIAN_MEETINGS_DIR>/Images/Screenshots`
- `DIARIZATION_ENABLED` / `DIARIZATION_PROVIDER`: legacy flags (UI/settings); **live recording does not run pyannote per chunk**. Speaker attribution paths:
  - **Offline (recommended):** `live-transcriber finalize` — WhisperX ASR + pyannote on `full_session.wav` (needs `uv sync --extra whisperx`, `HF_TOKEN`, Python ≤ 3.13 for torch). Uses `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS` / `DIARIZATION_NUM_SPEAKERS` when diarization runs inside finalize.
  - **Live dual-channel:** `TRANSCRIPTION_PROVIDER=faster_whisper`, `AUDIO_CHANNELS=2`, `AUDIO_STEREO_MODE=dual_path` — transcribes mic (L) and system (R) separately with channel-based speaker keys (no pyannote during capture).
  - **Legacy batch code only:** `application/diarization_batch.py` can reprocess stored chunk WAVs if wired manually; there is **no** `live-transcriber diarize` CLI.
- `HF_TOKEN`: Hugging Face token (required for pyannote in **finalize**; accept model licenses on the Hub first).
- `PYANNOTE_MODEL`: default `pyannote/speaker-diarization-3.1` (offline finalize / optional `diarization` extra).
- `DIARIZATION_NUM_SPEAKERS`: optional exact speaker count for pyannote during finalize.
- `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS`: optional bounds when `DIARIZATION_NUM_SPEAKERS` is unset. `MIN` must be ≤ `MAX`.

**Offline finalize (WhisperX)** — the `live-transcriber finalize` re-transcription + diarization pass over `full_session.wav` (needs `uv sync --extra whisperx`, `HF_TOKEN`, Python ≤ 3.13 for torch):

- `FINALIZE_ON_SESSION_STOP`: default `false`. When `true` (and `HF_TOKEN` is set), stopping a recording automatically enqueues the offline finalize pass; otherwise run `live-transcriber finalize` manually.
- `WHISPERX_MODEL`: default `large-v3-turbo` — Whisper checkpoint used for the finalize re-transcription.
- `WHISPERX_DEVICE`: optional; compute device for the WhisperX ASR model — **`cpu` or `cuda` only** (WhisperX's ASR backend is CTranslate2, which has **no MPS/Metal backend**). Unset auto-selects `cuda` when available, otherwise `cpu`. On **Apple Silicon the ASR always runs on CPU** — an `mps` value (auto or explicit) is coerced to `cpu`, since CTranslate2 cannot use it.
- `WHISPERX_TORCH_DEVICE`: optional; overrides the torch device for alignment when it must differ from `WHISPERX_DEVICE`.
- `WHISPERX_COMPUTE_TYPE`: default `float16` — CTranslate2 compute type (e.g. `int8`, `float32`). `float16` has no efficient CPU path, so on CPU (incl. Apple Silicon) it is automatically downgraded to `int8`.
- `WHISPERX_BATCH_SIZE`: default `8` (1–64) — lower it (2–4) and/or pick a smaller `WHISPERX_MODEL` if transcription OOMs.
- `WHISPERX_LANGUAGE`: optional ISO code (e.g. `en`); leave empty for auto-detect.
- `WHISPERX_SKIP_ALIGNMENT`: default `false` — skip the word-alignment stage (faster, coarser timestamps).
- `WHISPERX_DIARIZE_DEVICE`: optional; device for the pyannote diarization model. Unset defaults to CPU when alignment uses CUDA/MPS (avoids a second GPU model OOMing); set to `cuda`/`cuda:0` to force GPU diarization if you have the VRAM.

Speaker CLI:

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
