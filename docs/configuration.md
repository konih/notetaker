## Configuration

Configuration is loaded via `pydantic-settings` from environment variables.

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

### Notes

- **Live vs offline speakers:** During `record`, chunks are transcribed as-is (mono mixdown or `dual_path` stereo with faster-whisper). Cluster labels (`speaker_1`, …) from pyannote appear after **`finalize`**, not on every live chunk when `DIARIZATION_ENABLED=true`.
- **Debug: only `speaker_1` after finalize** — Often mixed mono or too few speakers hinted; try `DIARIZATION_NUM_SPEAKERS=2`, `dual_path` capture, or longer sessions before finalize.
- Never commit real API keys or `HF_TOKEN`.
- By default, transcript text is not logged (privacy).
- Offline diarization runs **locally** (pyannote via WhisperX); it does not send audio to OpenAI.
