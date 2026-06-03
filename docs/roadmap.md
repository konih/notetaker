## Roadmap

### Recently completed (2026)

Shipped on `main` (see [`docs/configuration.md`](configuration.md) and [`docs/architecture.md`](architecture.md)):

- **Video import** — `transcribe-video` from local file or URL; ffmpeg + optional yt-dlp
- **Slide detection** — pluggable `frame_diff` / `ffmpeg_scene` strategies; env + CLI overrides
- **Preview workflow** — `slides preview` / `slides apply` without re-transcribing
- **Cleanup** — `cleanup` CLI (dry-run default) and TUI session delete share `CleanupService`
- **Offline speakers** — `finalize` (WhisperX + pyannote); live `dual_path` stereo hints with faster-whisper
- **TUI** — session browser, slide preview with parameter tuning
- **Tests / CI** — e2e smoke for video, slides, cleanup; CI installs ffmpeg for e2e job

### Phase 1 (current)

- CLI
- audio capture (PipeWire/PulseAudio monitor)
- chunked OpenAI transcription
- SQLite persistence
- Markdown export

### Phase 2

- speaker diarization polish (live record screen capture, richer TUI speaker UX)
- better realtime streaming / incremental transcription
- session search and filtering
- improved summaries (templates, metadata) — partial: structured summary + Obsidian export

### Phase 3

- web UI or Tauri UI
- live transcript view
- annotations and highlights
- meeting templates
- Jira/Confluence export
