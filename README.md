## live-meeting-transcriber

Local, extensible background transcription for browser/Teams meetings on **Linux and macOS**. Captures **system audio** — via PipeWire/PulseAudio monitor sources on Linux, or a driver-free **Core Audio process tap** on macOS 14.4+ (no BlackHole needed) — transcribes in **chunks**, persists timestamped transcript segments to **SQLite**, and can summarize and structure notes via an **LLM**. A **terminal UI (Textual)** provides live transcript, recording controls, session browser, and settings.

### Key goals

- **Cross-platform** system-audio capture: Linux PipeWire/PulseAudio monitor sources and macOS 14.4+ Core Audio process taps (both with an optional microphone mix)
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
| **Audio capture** | ffmpeg + pactl (Linux) / Core Audio tap (macOS) | Chunked WAV from monitor source or system tap (+ optional mic) | **Local**. |
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

Then, for **offline finalize / Speaker ID** to label speakers:

1. Accept the licence for the model finalize actually uses — [`pyannote/speaker-diarization-community-1`](https://hf.co/pyannote/speaker-diarization-community-1) — while logged in on Hugging Face.
2. Create a **read** token at <https://huggingface.co/settings/tokens> and set `HF_TOKEN` in `.env` (or your shell env).
3. Run **`live-transcriber doctor`** (or `task diarization:doctor`) to verify everything — it checks the extras, ffmpeg, token auth (missing vs invalid), gated-model access, and the resolved device, printing a fix for the first thing missing.

The first finalize downloads ~1 GB+ of weights (Whisper checkpoint + alignment + pyannote). On **Apple Silicon** the ASR runs on **CPU** automatically (WhisperX's CTranslate2 backend has no Metal/MPS support) — no configuration needed.

Optional **inline slide thumbnails in the TUI** ([textual-image](https://github.com/darrenburns/textual-image)):

```bash
uv sync --extra tui-image
```

Inline PNG preview works in **Kitty**, **WezTerm**, or **Ghostty** — not in Terminator or most default GNOME terminals. In Terminator, use **`o`** in slide preview to open the PNG with `xdg-open`, or install **`chafa`** for a coarse ASCII preview (`sudo apt install chafa`). See [`docs/install-desktop.md`](docs/install-desktop.md).

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

**Desktop / menu launcher:** see [`docs/install-desktop.md`](docs/install-desktop.md) for `task install:desktop`, XDG config at `~/.config/live-meeting-transcriber/.env`, and system dependencies.

### Ubuntu audio setup (PipeWire/PulseAudio)

This project captures **system output audio** using a *monitor source*, and by default **also mixes in your default microphone** so your side of the conversation is transcribed. Disable with `AUDIO_INCLUDE_MICROPHONE=false` or `live-transcriber record --no-microphone`.

- List sources:

```bash
pactl list short sources
```

- Typical monitor source names end with `.monitor`.

### macOS audio setup (Core Audio tap)

macOS is a first-class target. On **macOS 14.4+** system-output audio is captured with a driver-free **Core Audio process tap** — **no BlackHole or Loopback needed** (default `AUDIO_MACOS_SYSTEM_CAPTURE=auto`). The tap uses a tiny bundled Swift helper compiled on first use (needs the **Xcode command line tools**: `xcode-select --install`) and, on first capture, triggers the **"System Audio Recording Only"** permission prompt — approve it once.

- On **older macOS** (or when you set `AUDIO_MACOS_SYSTEM_CAPTURE=avfoundation`), add a loopback source such as [BlackHole](https://github.com/ExistentialAudio/BlackHole) and select it as the audio source.
- As on Linux, your default microphone is mixed in by default; disable with `AUDIO_INCLUDE_MICROPHONE=false` or `--no-microphone`.
- Offline diarization (`finalize`) runs on Apple Silicon — the ASR/compute device resolves to `cpu`/`int8` automatically (Core ML/MPS is not used for the CTranslate2 backend). Run `live-transcriber doctor` to verify prerequisites.

See **[docs/system-audio-capture.md](docs/system-audio-capture.md)** and the `AUDIO_MACOS_SYSTEM_CAPTURE` entry in [docs/configuration.md](docs/configuration.md) for details.

### CLI usage

Interactive terminal UI (live transcript, status, settings, session browser):

```bash
uv run live-transcriber tui
```

**Keyboard.** The always-visible footer shows only the core recording actions —
**`r`** record, **`x`** stop, **`k`** summarize, **`w`** export, **`q`** quit — so it fits
a standard terminal without clipping. Every other action stays one keystroke away and is
listed in the **command palette** (**`Ctrl+P`**): **`t`** edit meeting, **`s`** settings,
**`a`** audio sources, **`j`** jump to meeting, **`c`** ack errors, **`Ctrl+D`** speaker ID, and
**`Ctrl+1/2/3`** to switch the Live/Meetings/Logs tabs. Press **`?`** any time to open the
**keyboard-shortcut overlay** — a full, always-current list of the global and Meetings-tab
shortcuts (it reads the live keymap, so it can't drift). The status sidebar shows the
**log file path** after settings load.

**Browsing meetings.** The **Meetings tab is the single home** for browsing and managing
sessions: press **`/`** there to filter the list by free text (title/notes/attendees) and
date tokens — e.g. `standup after:2026-07-01 before:2026-07-31` (**`Esc`** clears the
filter). **`j`** opens the **jump-to-meeting picker** from anywhere: type a fuzzy query,
press **`Enter`**, and the meeting opens in the Meetings tab (**`c`** copies the session
ID from the picker).

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

Backfill any sessions whose auto-finalize-on-stop never completed (e.g. the app
was closed right after stopping) — finds ended sessions whose transcript is
still entirely `unknown` and re-runs finalize for each. Use `--dry-run` to list
them first:

```bash
uv run live-transcriber finalize-pending --dry-run
uv run live-transcriber finalize-pending
```

> When `FINALIZE_ON_SESSION_STOP=true` and `HF_TOKEN` is set, the TUI also
> re-runs finalize on startup for such sessions **ended within the last 24h**,
> so a normal stop-then-quit no longer silently loses diarization.

List and **search** sessions (filter by title, notes, or attendees):

```bash
uv run live-transcriber sessions                  # all sessions, newest first
uv run live-transcriber sessions --search platform  # -s: case-insensitive substring
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

CI (GitHub Actions) runs **pytest** (with a coverage floor), **mypy** (`typecheck` job, `--all-extras`), **Ruff** (lint + format check), an **e2e smoke** (ffmpeg), and **gitleaks** for secrets.

### Testing strategy

- Unit tests mock audio and external APIs (no real OpenAI calls).
- The integration lane (`task test:integration`, CI `integration` job) is deterministic — it mocks network boundaries (e.g. yt-dlp) and runs against committed fixtures; it needs **ffmpeg** and is skipped if that's absent.

### Known limitations (current)

- Uses **chunked transcription** (not low-latency streaming yet).
- **Live `record`** does not run pyannote per chunk; speaker clusters come from **`finalize`** (WhisperX) or **`dual_path`** stereo with faster-whisper during capture.
- **WhisperX / pyannote** (offline `finalize`, optional legacy diarization extras) need **Python ≤ 3.13** until PyTorch publishes **cp314** wheels.
- Diarization labels **clusters**, not legal identities — use aliases for real names.
- Terminal UI is local-only; a web/desktop shell could reuse the same store/effects pattern later.

### Roadmap

See `docs/roadmap.md`.
