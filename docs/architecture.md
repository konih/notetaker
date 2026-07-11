## Architecture

This project follows **clean / hexagonal architecture**:

- **Domain** (`live_meeting_transcriber/domain`): pure models, events, and ports (interfaces). No provider code.
- **Application** (`live_meeting_transcriber/application`): orchestration and use-cases (record session, summarize session).
- **Adapters**:
  - **Audio** (`live_meeting_transcriber/audio`): system audio capture + device listing. Linux uses ffmpeg + PipeWire/PulseAudio; macOS uses ffmpeg + AVFoundation, and on macOS 14.4+ a driver-free **Core Audio process tap** (`coreaudio_tap.py` + the Swift helper in `native/macos/`) captures system output without BlackHole. Backend selection lives in `backend.py`/`platform.py`.
  - **Transcription** (`live_meeting_transcriber/transcription`): provider implementations (OpenAI, faster-whisper) behind ports.
  - **Summarization** (`live_meeting_transcriber/summarization`): provider implementations behind ports.
  - **Diarization** (`live_meeting_transcriber/diarization`): pyannote adapters (`NoopDiarizationProvider`, `PyannoteDiarizationProvider`) and overlap-based **merge** into `TranscriptSegment.speaker`. **Live `record` does not call pyannote per chunk**; speaker labels from clustering appear after offline **`finalize`** (WhisperX + pyannote on `full_session.wav`). Legacy batch code can still diarize stored chunk WAVs if wired manually.
  - **Offline finalize** (`live_meeting_transcriber/offline`): full-session ASR + diarization behind the `OfflineTranscriber` port. Two engines behind one entry point (`whisperx_pipeline.py`), selected by `OFFLINE_ASR_ENGINE`: WhisperX/CTranslate2 (+ wav2vec2 alignment) and **MLX** (`mlx_asr.py`, mlx-whisper on the Apple GPU; macOS-arm64-only `mlx` extra). The MLX path assigns speakers with the pure interval-overlap function in `domain/speaker_overlap.py` (no wav2vec2), gates hallucination-on-silence segments by window RMS, and degrades to the WhisperX path with a logged warning when MLX cannot run — an engine preference never fails finalize.
  - **Storage** (`live_meeting_transcriber/storage`): SQLite repositories behind ports.
  - **Observability** (`live_meeting_transcriber/observability`): structured logging.
  - **Screenshot export** (`application/screenshot_export.py`): match GNOME screenshot filenames to session bounds; copies into `exports/screenshots/<session_id>/` and optional Obsidian `Images/Screenshots`, interleaved in transcript markdown.
  - **Video** (`live_meeting_transcriber/video/`): pluggable slide detection behind the `SlideDetectionStrategy` port — `strategies/frame_diff.py` (periodic grayscale diff), `strategies/ffmpeg_scene.py` (ffmpeg scene filter), factory in `strategies/factory.py`; shared frame extraction in `slide_common.py`.
  - **Slide preview** (`application/slide_preview_service.py`): re-run detection on an imported session's stored source video without re-transcribing; writes preview thumbnails, then `slides apply` saves approved PNGs + `slides.json`.
  - **Cleanup** (`application/cleanup_service.py`): purge session artifacts (chunks, session audio/slides/source video, slide preview cache, exports) shared by CLI `cleanup` (dry-run default) and TUI session delete.

### Provider abstraction

Provider-specific code must not leak into application/domain logic.

- Domain defines `TranscriptionProvider`, `DiarizationProvider`, `DiarizationRepository`, `SpeakerAliasRepository`, `SummarizationProvider`, etc.
- Application depends only on ports.
- Adapters implement those ports (OpenAI now; replaceable later).

### Enforcement (import-linter)

Boundaries are checked automatically, not just by review. [Import Linter](https://import-linter.readthedocs.io/)
contracts live in [`.importlinter`](../.importlinter); the decision memo, violation inventory, and
rollout plan are in [`architecture-guardrails.md`](architecture-guardrails.md).

- **Blocking today:** `domain-independence` — the domain layer must import nothing from
  application/adapters/UI/CLI. Gated by `tests/architecture/test_import_contracts.py`, so it runs
  in `task check` and CI.
- **Report-only (pilot):** `application-independent-of-adapters` and `adapters-do-not-import-upward`
  document known debt. Run `task arch:check` (never fails) for the full report; a non-blocking CI
  `arch` job does the same. These promote to blocking per story **A9** as the A-epic refactors land.

### Audio pipeline

Phase 1 uses robust Linux tooling:

- List sources using `pactl list short sources`
- Capture audio using `ffmpeg -f pulse -i <source>` into temporary WAV chunks
- Normalize to 16kHz mono (configurable)
- Transcribe each chunk and append timestamped `TranscriptSegment`s
- By default, **monitor + microphone** are mixed with ffmpeg `amix` (two `-f pulse` inputs) so transcripts include your voice as well as meeting playback.

Near-silent chunks are **not** sent to the transcriber (F1): after a chunk is appended to
`full_session.wav`, the recorder measures its RMS level (`audio/wav_level.py`) and skips live
transcription when it falls below `AUDIO_SILENCE_THRESHOLD_DBFS` (pure decision in
`application/silence.py`; see [`docs/configuration.md`](configuration.md)). Offline finalize
still sees the complete session audio.

TODOs:
- Real-time low-latency streaming

### Video import and slide detection

Applies to **`live-transcriber transcribe-video`** (local file or URL via yt-dlp). Live **`record`** sessions do not extract slides from screen capture; GNOME screenshot filename matching on export is separate (`screenshot_export.py`).

1. **Import** — `VideoImportService` resolves the source, stores a copy under app data, extracts audio to WAV, and transcribes into a new session (same chunk pipeline as live capture, but from media file).
2. **Detect** — `SlideDetectionStrategy` adapters (`frame_diff`, `ffmpeg_scene`) score frame changes; shared extraction lives in `slide_common.py`; factory reads `VIDEO_SLIDE_*` (see [`docs/configuration.md`](configuration.md)).
3. **Review** — inline y/n/a/q prompts (`slide_review.py`) on import, or **`slides preview`** → tune params without re-transcribing → **`slides apply`** to save PNGs + `slides.json`.
4. **Export** — markdown export interleaves slide PNGs with transcript lines (alongside optional GNOME screenshots).
5. **Cleanup** — `CleanupService` purges session artifacts (chunks, audio, slides, source video, preview cache, exports); CLI **`cleanup`** is dry-run by default; TUI session delete uses the same helper.

Parameter matrix, preview workflow, and cleanup flags: [`docs/configuration.md`](configuration.md).

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

**Live capture:** chunks are transcribed as-is (mono mixdown or `dual_path` stereo with faster-whisper). No pyannote pass runs during `record` even when `DIARIZATION_ENABLED=true`.

**Offline finalize (recommended):** `live-transcriber finalize` runs WhisperX ASR + pyannote on `full_session.wav`, then **`merge_service`** assigns each transcript interval the diarization `speaker_key` with the **largest time overlap**; if none, `unknown` (shown as **Unknown Speaker** in exports unless aliased).

**Legacy adapters:** `DiarizationProvider.diarize_chunk` still exists on the pyannote/noop adapters as an extension point, but no application code wires it — the unused `diarization_batch` reprocessor was removed (A7), and there is no `live-transcriber diarize` CLI.

- **Persistence**: raw intervals live in `diarization_segments`; display names per session in `session_speaker_names` (`SpeakerAliasRepository` / CLI `speaker-alias`).
- **Pyannote** is an **optional** extra (`whisperx` / `diarization`); needs `HF_TOKEN` and accepted Hub model licenses for finalize.

**Diarization vs identification:** diarization clusters speakers (`speaker_1`, `speaker_2`, …). It does **not** know real names; map clusters with **`speaker-alias`** or the Meetings tab speaker fields.
