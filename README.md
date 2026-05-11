## live-meeting-transcriber

Local, extensible background transcription for browser/Teams meetings on **Ubuntu Linux**. Captures **system audio** via PipeWire/PulseAudio monitor sources, transcribes in **chunks**, persists timestamped transcript segments to **SQLite**, and can summarize and structure notes via an **LLM**. A **terminal UI (Textual)** provides live transcript, recording controls, session browser, and settings.

### Key goals

- **Linux-first** audio capture (PipeWire/PulseAudio monitor + optional microphone mix)
- **Provider abstraction** (OpenAI today; architecture supports swapping in local Whisper, Azure, Ollama, etc.)
- **Clean / hexagonal architecture** with strict boundaries (`docs/architecture.md`)
- **CLI + TUI** — scriptable commands and a full-screen terminal experience
- **TDD**, strong typing (Ruff in CI), structured logging

### Security & privacy

- Transcripts may contain confidential information.
- **Audio** for each chunk is sent to whatever **transcription** backend you configure (default: OpenAI). **Summaries** send transcript text to the **LLM** backend (default: OpenAI). Diarization runs **locally** when pyannote is enabled (no audio leaves your machine for that step).
- Meeting metadata, transcripts, summaries, and diarization segments stay in **local SQLite** unless you export or copy files elsewhere.
- You are responsible for consent and legal compliance before recording meetings.

### Models, backends, and where they run

Everything below is configured via `.env` (see `.env.example` and `docs/configuration.md`). **“Local”** means processes on your machine; **“cloud”** means a network API.

| Capability | Default | Typical model / stack | Runs |
|------------|---------|------------------------|------|
| **Transcription** | OpenAI | `TRANSCRIPTION_MODEL` (default **`gpt-4o-mini-transcribe`**) — OpenAI **Audio** transcriptions API | **Cloud** (OpenAI). Requires `OPENAI_API_KEY`. |
| **Summarization** | OpenAI | `SUMMARY_MODEL` (default **`gpt-4o-mini`**) — chat/completions with structured JSON for summary + decisions + action items | **Cloud** (OpenAI). Same API key. |
| **Diarization** | Disabled (`noop`) | **`DIARIZATION_PROVIDER=noop`**: no ML, no extra deps | **Local** (trivial). |
| **Diarization** (optional) | pyannote | `PYANNOTE_MODEL` (default **`pyannote/speaker-diarization-3.1`**) via **pyannote.audio** / PyTorch | **Local** inference. Weights downloaded from **Hugging Face** (`HF_TOKEN`); GPU recommended, CPU possible. Install: `uv sync --extra diarization`. |
| **Storage** | SQLite | File at `DATABASE_URL` | **Local** only. |
| **Audio capture** | ffmpeg + pactl | Chunked WAV from monitor (+ optional mic) | **Local**. |
| **TUI** | Textual | No separate “model”; UI only | **Local**. |

**Provider fields in settings:** `TRANSCRIPTION_PROVIDER` and `LLM_PROVIDER` are currently **`openai`** only in code; other values are reserved for future adapters. Replacing OpenAI means implementing the domain ports and wiring the container — the rest of the app stays the same.

**Diarization caveat:** pyannote outputs **speaker clusters** (e.g. `SPEAKER_00`), not real-world identities. Use **`speaker-alias`** / the TUI to map clusters to names.

### Installation (uv)

```bash
uv sync --all-extras
```

Optional **speaker diarization** (pyannote / PyTorch — large download):

```bash
uv sync --extra diarization
```

Accept the **pyannote** and model license(s) on Hugging Face, then set `HF_TOKEN` in `.env`.

### Configuration

Copy `.env.example` to `.env` and edit:

- `OPENAI_API_KEY` (required for default transcription + summarization)
- `DATABASE_URL`
- `TRANSCRIPTION_MODEL`, `SUMMARY_MODEL`
- `AUDIO_CHUNK_SECONDS`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`
- `DIARIZATION_ENABLED`, `DIARIZATION_PROVIDER`, `HF_TOKEN`, `PYANNOTE_MODEL` (optional)
- `LOG_FILE` / `LOG_ENABLE_FILE` — structured JSON logs (default: under `~/.local/share/live-meeting-transcriber/logs/`)

Full reference: `docs/configuration.md`.

### Ubuntu audio setup (PipeWire/PulseAudio)

This project captures **system output audio** using a *monitor source*, and by default **also mixes in your default microphone** so your side of the conversation is transcribed. Disable with `AUDIO_INCLUDE_MICROPHONE=false` or `live-transcriber record --no-microphone`.

- List sources:

```bash
pactl list short sources
```

- Typical monitor source names end with `.monitor`.

### CLI usage

Interactive terminal UI (live transcript, status, settings, session browser):

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

Exports can **attach screenshots** from `~/Pictures/Screenshots` when filenames look like `Screenshot from 2026-05-11 09-24-01.png`: they are copied next to the export and, if Obsidian paths are configured, into `Images/Screenshots` with embeds placed after the transcript line for that time range. See `docs/configuration.md` (`SCREENSHOTS_*`, `OBSIDIAN_SCREENSHOTS_DIR`).

Speaker diarization (after enabling `DIARIZATION_*` in `.env`; see `docs/configuration.md`):

```bash
uv run live-transcriber speakers --session-id <id>
uv run live-transcriber speaker-alias --session-id <id> --speaker speaker_1 --name "Konrad"
uv run live-transcriber diarize --session-id <id>
```

### Developer workflow (Taskfile)

```bash
task install
task check
task test
task lint
task typecheck
```

CI (GitHub Actions) runs **pytest**, **Ruff** (lint + format check), and **gitleaks** for secrets. **mypy** is not enforced yet (`task typecheck` may report issues).

### Testing strategy

- Unit tests mock audio and external APIs (no real OpenAI calls).
- Integration tests are skipped unless `RUN_INTEGRATION_TESTS=1`.

### Known limitations (current)

- Uses **chunked transcription** (not low-latency streaming yet).
- Diarization is **optional** (pyannote): extra install, GPU recommended, model access via Hugging Face; chunk processing adds latency.
- Diarization labels **clusters**, not legal identities — use aliases for real names.
- Terminal UI is local-only; a web/desktop shell could reuse the same store/effects pattern later.

### Roadmap

See `docs/roadmap.md`.
