## Configuration

Configuration is loaded via `pydantic-settings` from environment variables.

### Environment variables

- `OPENAI_API_KEY`: required when `TRANSCRIPTION_PROVIDER=openai` or `LLM_PROVIDER=openai`
- `TRANSCRIPTION_PROVIDER`: `openai` (default)
- `LLM_PROVIDER`: `openai` (default)
- `TRANSCRIPTION_MODEL`: default `gpt-4o-mini-transcribe`
- `SUMMARY_MODEL`: default `gpt-4o-mini`
- `DATABASE_URL`: default `sqlite:////home/you/.local/share/live-meeting-transcriber/app.db`
- `AUDIO_CHUNK_SECONDS`: default `10`
- `AUDIO_SAMPLE_RATE`: default `16000`
- `AUDIO_CHANNELS`: default `1`
- `AUDIO_INCLUDE_MICROPHONE`: default `true` — mix **default monitor** (system/meeting playback) with **default microphone** (your voice) via ffmpeg `amix`
- `AUDIO_MICROPHONE_SOURCE`: optional explicit PulseAudio source name for the mic leg (see `live-transcriber devices`, marked with `^`)
- `LOG_LEVEL`: default `INFO`
- `LOG_ENABLE_FILE`: default `true` — append structured JSON lines to a rotating log file
- `LOG_FILE`: optional absolute path; default is under the app data directory (`…/logs/live-meeting-transcriber.log`)
- `LOG_FILE_MAX_MB`: rotation size per file (default `10`)
- `LOG_FILE_BACKUP_COUNT`: number of rotated backups to keep (default `5`)
- `KEEP_AUDIO_CHUNKS`: default `0`
- `SCREENSHOTS_EXPORT_ENABLED`: default `true` — embed matching screenshots in markdown exports
- `SCREENSHOTS_SOURCE_DIR`: optional; default `~/Pictures/Screenshots` (GNOME filenames `Screenshot from YYYY-MM-DD HH-MM-SS.png`)
- `OBSIDIAN_SCREENSHOTS_DIR`: optional; default `<parent of OBSIDIAN_MEETINGS_DIR>/Images/Screenshots`
- `DIARIZATION_ENABLED`: default `false` — when `true`, each recorded chunk is diarized after transcription (may add latency).
- `DIARIZATION_PROVIDER`: `noop` (default) or `pyannote`
- `HF_TOKEN`: Hugging Face access token (required for `pyannote`; accept model licenses on the Hub first).
- `PYANNOTE_MODEL`: default `pyannote/speaker-diarization-3.1`

Optional CLI:

- `live-transcriber diarize --session-id <uuid>` — re-run diarization on saved chunk WAVs under the app data dir (needs `KEEP_AUDIO_CHUNKS` or existing files).
- `live-transcriber speakers --session-id <uuid>` — transcript keys, stored diarization keys, aliases.
- `live-transcriber speaker-alias --session-id <uuid> --speaker speaker_1 --name "Konrad"` (also accepts `SPEAKER_00`-style labels; normalized to `speaker_*` keys).

### Notes

- Never commit real API keys or `HF_TOKEN`.
- By default, transcript text is not logged (privacy).
- Diarization sends **audio** to a local model (pyannote); it does not replace OpenAI transcription unless you change providers separately.
