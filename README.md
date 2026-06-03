## live-meeting-transcriber

Local, extensible background transcription for browser/Teams meetings on **Ubuntu Linux**. Captures **system audio** via PipeWire/PulseAudio monitor sources, transcribes in **chunks**, persists timestamped transcript segments to **SQLite**, and can summarize and structure notes via an **LLM**. A **terminal UI (Textual)** provides live transcript, recording controls, session browser, and settings.

### Key goals

- **Linux-first** audio capture (PipeWire/PulseAudio monitor + optional microphone mix)
- **Provider abstraction** — OpenAI or **local faster-whisper** for transcription; OpenAI for summaries today (more LLM backends can follow the same ports)
- **Clean / hexagonal architecture** with strict boundaries (`docs/architecture.md`)
- **CLI + TUI** — scriptable commands and a full-screen terminal experience
- **TDD**, strong typing (Ruff in CI), structured logging

### Security & privacy

- Transcripts may contain confidential information.
- **Audio** for each chunk is sent to the **transcription** backend only when that backend is cloud-based (default: OpenAI). With **`TRANSCRIPTION_PROVIDER=faster_whisper`**, chunk audio stays on disk and is processed **locally**. **Summaries** still send transcript text to the **LLM** backend (default: OpenAI) unless you add a local LLM adapter. Diarization runs **locally** when pyannote is enabled.
- Meeting metadata, transcripts, summaries, and diarization segments stay in **local SQLite** unless you export or copy files elsewhere.
- You are responsible for consent and legal compliance before recording meetings.

### Models, backends, and where they run

Everything below is configured via `.env` (see `.env.example` and `docs/configuration.md`). **“Local”** means processes on your machine; **“cloud”** means a network API.

| Capability | Default | Typical model / stack | Runs |
|------------|---------|------------------------|------|
| **Transcription** | OpenAI | `TRANSCRIPTION_MODEL` (default **`gpt-4o-mini-transcribe`**) — OpenAI **Audio** transcriptions API | **Cloud** (OpenAI). Requires `OPENAI_API_KEY`. |
| **Transcription** (optional) | faster-whisper | `FASTER_WHISPER_MODEL` (default **`small`**) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2 | **Local**. No audio sent for STT. Install: `uv sync --extra faster-whisper`. Set `TRANSCRIPTION_PROVIDER=faster_whisper`. |
| **Summarization** | OpenAI | `SUMMARY_MODEL` (default **`gpt-4o-mini`**) — chat/completions with structured JSON for summary + decisions + action items | **Cloud** (OpenAI). Same API key. |
| **Diarization** | Disabled (`noop`) | **`DIARIZATION_PROVIDER=noop`**: no ML, no extra deps | **Local** (trivial). |
| **Diarization** (optional) | pyannote | `PYANNOTE_MODEL` (default **`pyannote/speaker-diarization-3.1`**) via **pyannote.audio** / PyTorch | **Local** inference. Weights downloaded from **Hugging Face** (`HF_TOKEN`); GPU recommended, CPU possible. Install: `uv sync --extra diarization`. |
| **Storage** | SQLite | File at `DATABASE_URL` | **Local** only. |
| **Audio capture** | ffmpeg + pactl | Chunked WAV from monitor (+ optional mic) | **Local**. |
| **TUI** | Textual | No separate “model”; UI only | **Local**. |

**Provider fields in settings:** `TRANSCRIPTION_PROVIDER` is **`openai`** or **`faster_whisper`**. `LLM_PROVIDER` is **`openai`** only for now (summaries / structured extraction). Fully offline operation would add a local LLM adapter the same way.

**Diarization caveat:** pyannote outputs **speaker clusters** (e.g. `SPEAKER_00`), not real-world identities. Use **`speaker-alias`** / the TUI to map clusters to names.

### Installation (uv)

**Python version:** The core app supports **3.12+**. Extras **`whisperx`** and **`diarization`** depend on **PyTorch**, which (as of early 2026) provides wheels only up to **3.13** — on **CPython 3.14** those extras are omitted so `uv sync` still succeeds. For offline finalize / pyannote, use **`uv python pin 3.13`** (or 3.12) in this repo, then `uv sync --extra whisperx` (and/or `--extra diarization`).

```bash
uv sync --all-extras
```

Optional **local transcription** (faster-whisper):

```bash
uv sync --extra faster-whisper
```

Set `TRANSCRIPTION_PROVIDER=faster_whisper` in `.env`. You still need `OPENAI_API_KEY` if you use the default OpenAI summarizer.

Optional **speaker diarization** (pyannote / PyTorch — large download):

```bash
uv sync --extra diarization
```

Accept the **pyannote** and model license(s) on Hugging Face, then set `HF_TOKEN` in `.env`.

### Configuration

Copy `.env.example` to `.env` and edit:

- `OPENAI_API_KEY` (required for OpenAI transcription and/or default summarization)
- `DATABASE_URL`
- `TRANSCRIPTION_PROVIDER` (`openai` or `faster_whisper`)
- `TRANSCRIPTION_MODEL`, `SUMMARY_MODEL` (OpenAI); `FASTER_WHISPER_*` when using faster-whisper
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

Transcribe a video file or URL (presentation talks, recorded meetings). Downloads go to the app data dir (not the repo). Requires **ffmpeg**; URLs also need **yt-dlp**. Slide changes are detected from frame diffs, then you review candidates interactively so only real slides are saved:

```bash
uv run live-transcriber transcribe-video --source /path/to/talk.mp4
uv run live-transcriber transcribe-video --source "https://www.youtube.com/watch?v=..."
# Skip slide prompts (accept all candidates):
uv run live-transcriber transcribe-video --source talk.mp4 --yes-slides
# Transcript only:
uv run live-transcriber transcribe-video --source talk.mp4 --no-slides
```

Tune slide detection via `VIDEO_SLIDE_*` in `.env` (sample interval, change threshold, minimum seconds between slides, max candidates). Saved slides appear in exports alongside GNOME screenshots.

Install video prerequisites (ffmpeg + yt-dlp) and fetch test fixtures (meeting speech EN/DE + presentation clips):

```bash
task install:video-prereqs
task fixtures:fetch             # meeting WAVs + presentation MP4s (see docs/test-fixtures.md)
task test:e2e
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

Offline WhisperX + speaker attribution (install **`uv sync --extra whisperx`**, set **`HF_TOKEN`**; needs Python **3.12 or 3.13** for PyTorch):

```bash
uv run live-transcriber finalize --session-id <id>
```

Speaker keys and display names (see `docs/configuration.md`):

```bash
uv run live-transcriber speakers --session-id <id>
uv run live-transcriber speaker-alias --session-id <id> --speaker speaker_1 --name "Konrad"
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
- **Live `record`** does not run pyannote per chunk; speaker clusters come from **`finalize`** (WhisperX) or **`dual_path`** stereo with faster-whisper during capture.
- **WhisperX / pyannote** (offline `finalize`, optional legacy diarization extras) need **Python ≤ 3.13** until PyTorch publishes **cp314** wheels.
- Diarization labels **clusters**, not legal identities — use aliases for real names.
- Terminal UI is local-only; a web/desktop shell could reuse the same store/effects pattern later.

### Roadmap

See `docs/roadmap.md`.
