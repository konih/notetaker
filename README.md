## live-meeting-transcriber

Local, extensible background transcription for browser/Teams meetings on **Ubuntu Linux**. Captures **system audio** via PipeWire/PulseAudio monitor sources, transcribes in **chunks**, persists timestamped transcript segments to **SQLite**, and can later summarize/annotate via an LLM.

### Key goals

- **Linux-first** audio capture (PipeWire/PulseAudio monitor sources)
- **Provider abstraction** (OpenAI now; replaceable with local Whisper, Azure OpenAI, Ollama, etc.)
- **Clean/hexagonal architecture** with strict boundaries
- **CLI-first**, background-friendly (no UI yet)
- **TDD**, strong typing, structured logging

### Security & privacy

- Transcripts may contain confidential information.
- Data is stored locally; audio is only uploaded to the configured transcription provider.
- You are responsible for consent/legal compliance before recording meetings.

### Installation (uv)

```bash
uv sync --all-extras
```

### Configuration

Copy `.env.example` to `.env` and edit:

- `OPENAI_API_KEY`
- `DATABASE_URL`
- `AUDIO_CHUNK_SECONDS`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`
- `TRANSCRIPTION_MODEL`, `SUMMARY_MODEL`
- `LOG_FILE` / `LOG_ENABLE_FILE` — structured JSON logs (default: under `~/.local/share/live-meeting-transcriber/logs/`)

### Ubuntu audio setup (PipeWire/PulseAudio)

This project captures **system output audio** using a *monitor source*.

- List sources:

```bash
pactl list short sources
```

- Typical monitor source names end with `.monitor`.

### CLI usage

Interactive terminal UI (live transcript, status, settings panel):

```bash
uv run live-transcriber tui
```

In the TUI, **`m`** opens **Sessions** (browse SQLite sessions, **`r`** refresh, **`e`** rename). The status sidebar shows the **log file path** after settings load.

List available sources:

```bash
uv run live-transcriber devices
```

Record and transcribe (chunked):

```bash
uv run live-transcriber record --title "Weekly sync" --chunk-seconds 10
```

Summarize a session:

```bash
uv run live-transcriber summarize --session-id <id>
```

Export Markdown:

```bash
uv run live-transcriber export --session-id <id> --format markdown
```

### Developer workflow (Taskfile)

```bash
task install
task check
task test
task lint
task typecheck
```

### Testing strategy

- Unit tests mock audio and external APIs (no real OpenAI calls).
- Integration tests are skipped unless `RUN_INTEGRATION_TESTS=1`.

### Known limitations (current)

- Uses **chunked transcription** (not low-latency streaming yet).
- Diarization is stubbed (noop).
- Terminal UI is local-only; a web/desktop shell can reuse the same store/effects pattern later.

### Roadmap

See `docs/roadmap.md`.
