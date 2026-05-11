## Architecture

This project follows **clean / hexagonal architecture**:

- **Domain** (`live_meeting_transcriber/domain`): pure models, events, and ports (interfaces). No provider code.
- **Application** (`live_meeting_transcriber/application`): orchestration and use-cases (record session, summarize session).
- **Adapters**:
  - **Audio** (`live_meeting_transcriber/audio`): Linux system audio capture + device listing.
  - **Transcription** (`live_meeting_transcriber/transcription`): provider implementations (OpenAI) behind ports.
  - **Summarization** (`live_meeting_transcriber/summarization`): provider implementations behind ports.
  - **Diarization** (`live_meeting_transcriber/diarization`): optional chunk-level diarization (`NoopDiarizationProvider`, `PyannoteDiarizationProvider`) plus overlap-based **merge** into `TranscriptSegment.speaker`.
  - **Storage** (`live_meeting_transcriber/storage`): SQLite repositories behind ports.
  - **Observability** (`live_meeting_transcriber/observability`): structured logging.
  - **Screenshot export** (`application/screenshot_export.py`): match GNOME screenshot filenames to session bounds; copies into `exports/screenshots/<session_id>/` and optional Obsidian `Images/Screenshots`, interleaved in transcript markdown.

### Provider abstraction

Provider-specific code must not leak into application/domain logic.

- Domain defines `TranscriptionProvider`, `DiarizationProvider`, `DiarizationRepository`, `SpeakerAliasRepository`, `SummarizationProvider`, etc.
- Application depends only on ports.
- Adapters implement those ports (OpenAI now; replaceable later).

### Audio pipeline

Phase 1 uses robust Linux tooling:

- List sources using `pactl list short sources`
- Capture audio using `ffmpeg -f pulse -i <source>` into temporary WAV chunks
- Normalize to 16kHz mono (configurable)
- Transcribe each chunk and append timestamped `TranscriptSegment`s
- By default, **monitor + microphone** are mixed with ffmpeg `amix` (two `-f pulse` inputs) so transcripts include your voice as well as meeting playback.

TODOs:
- Real-time low-latency streaming
- Better VAD (voice activity detection) to skip silent chunks

### Terminal UI (Textual)

The **TUI** (`live_meeting_transcriber/ui/`) is intentionally decoupled from business logic:

- **Application events** (`domain/application_events.py`) are emitted by the recorder; a **bridge** maps them to UI actions.
- **UI state** follows a Redux-like pattern: immutable `AppState`, typed `Action`s, a **pure reducer**, **selectors**, and a **Store** (`dispatch` / `subscribe`).
- **Side effects** (start/stop recording, load settings) live in `ui/effects/` and run **outside** the reducer.

The same application services remain usable from a future **FastAPI** backend, **React** client, or **Tauri** shell without rewriting transcription or storage.

### Planned rich UI integration

Beyond the terminal UI, the application layer is designed so:

- **FastAPI** can call the same application services
- a **React** UI can consume a REST/WebSocket API
- a **Tauri** shell can embed local web UI and talk to the same backend

### Diarization

- **`DiarizationProvider.diarize_chunk`**: returns `list[DiarizationSegment]` (absolute timestamps) for one WAV chunk.
- **`merge_service`**: assigns each transcript interval the diarization `speaker_key` with the **largest time overlap**; if none, `unknown` (shown as **Unknown Speaker** in exports unless aliased).
- **Persistence**: raw intervals live in `diarization_segments`; display names per session in `session_speaker_names` (`SpeakerAliasRepository` / CLI `speaker-alias`).
- **Pyannote** is an **optional** extra; the app runs without it when `DIARIZATION_PROVIDER=noop` or `DIARIZATION_ENABLED=false`.

**Diarization vs identification:** diarization clusters speakers (Speaker 1, Speaker 2). It does **not** know real names; map clusters with **`speaker-alias`** or the Meetings tab speaker fields.
