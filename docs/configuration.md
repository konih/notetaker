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
- `LOG_LEVEL`: default `INFO`
- `LOG_ENABLE_FILE`: default `true` — append structured JSON lines to a rotating log file
- `LOG_FILE`: optional absolute path; default is under the app data directory (`…/logs/live-meeting-transcriber.log`)
- `LOG_FILE_MAX_MB`: rotation size per file (default `10`)
- `LOG_FILE_BACKUP_COUNT`: number of rotated backups to keep (default `5`)
- `KEEP_AUDIO_CHUNKS`: default `0`
- `DIARIZATION_ENABLED`: default `false` (UI + future providers)
- `DIARIZATION_PROVIDER`: default `noop`

### Notes

- Never commit real API keys.
- By default, transcript text is not logged (privacy).
