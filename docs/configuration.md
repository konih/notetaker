## Configuration

Configuration is loaded via `pydantic-settings` from environment variables and `.env` files.

### `.env` file locations

Files are read in order; **later files override earlier ones**:

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
- `AUDIO_INCLUDE_MICROPHONE`: default `true` — mix **default monitor** (system/meeting playback) with **default microphone** (your voice) via ffmpeg `amix`
- `AUDIO_MICROPHONE_SOURCE`: optional explicit PulseAudio source name for the mic leg (see `live-transcriber devices`, marked with `^`)

> **Capturing Teams/Zoom/Meet audio (both sides of a call):** the default captures only
> your microphone. To also transcribe remote participants you must add a loopback source
> (BlackHole on macOS; PipeWire/PulseAudio `.monitor` on Linux). See
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
- `OBSIDIAN_SCREENSHOTS_DIR`: optional; default `<parent of OBSIDIAN_MEETINGS_DIR>/Images/Screenshots`
- `DIARIZATION_ENABLED` / `DIARIZATION_PROVIDER`: legacy flags (UI/settings); **live recording does not run pyannote per chunk**. Speaker attribution paths:
  - **Offline (recommended):** `live-transcriber finalize` — WhisperX ASR + pyannote on `full_session.wav` (needs `uv sync --extra whisperx`, `HF_TOKEN`, Python ≤ 3.13 for torch). Uses `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS` / `DIARIZATION_NUM_SPEAKERS` when diarization runs inside finalize.
  - **Live dual-channel:** `TRANSCRIPTION_PROVIDER=faster_whisper`, `AUDIO_CHANNELS=2`, `AUDIO_STEREO_MODE=dual_path` — transcribes mic (L) and system (R) separately with channel-based speaker keys (no pyannote during capture).
  - **Legacy batch code only:** `application/diarization_batch.py` can reprocess stored chunk WAVs if wired manually; there is **no** `live-transcriber diarize` CLI.
- `HF_TOKEN`: Hugging Face token (required for pyannote in **finalize**; accept model licenses on the Hub first).
- `PYANNOTE_MODEL`: default `pyannote/speaker-diarization-3.1` (offline finalize / optional `diarization` extra).
- `DIARIZATION_NUM_SPEAKERS`: optional exact speaker count for pyannote during finalize.
- `DIARIZATION_MIN_SPEAKERS` / `DIARIZATION_MAX_SPEAKERS`: optional bounds when `DIARIZATION_NUM_SPEAKERS` is unset. `MIN` must be ≤ `MAX`.

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
