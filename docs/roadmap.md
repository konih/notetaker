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

## Proposals / stories

### Deterministic self-speaker label for the microphone channel (no diarization)

**Ask:** When I speak into the microphone, the transcript speaker should always be a
fixed configured name (e.g. `Konrad Heimel`) — no diarization needed for my own voice.

**Is it possible given we mix the audio?** Yes — but only when we *don't* mix.

- **`mixdown` (current default, `AUDIO_CHANNELS=2` → RMS mono):** mic (L) and system (R)
  are summed into one mono stream before transcription. Once mixed, there is no channel
  left to attribute a segment to, so a deterministic "this segment is me" label is
  impossible without diarization. This is the mode the reporter was on, which is why the
  ask isn't achievable there.
- **`dual_path` (`AUDIO_STEREO_MODE=dual_path`, faster-whisper only):** L (mic) and R
  (system) are kept separate and transcribed independently. The recorder *already* labels
  the mic side `YOU` and the system side `REMOTE`
  (`transcription/faster_whisper_transcriber.py::_transcribe_stereo_sync`). Because the
  attribution is by physical channel, it is 100% deterministic and needs no diarization.

**Proposed work:**

1. Add config `SELF_SPEAKER_NAME` (default unset). When set, the mic channel in `dual_path`
   is labeled with that name instead of `YOU`; optionally add `REMOTE_SPEAKER_NAME` for the
   system side (default keep `REMOTE`).
2. Thread the name from `Settings` → `Recorder`/`FasterWhisperTranscriptionProvider` so the
   `speaker=` field on mic segments is the configured name at creation time (no post-hoc
   remap, no diarization pass).
3. UX: when `SELF_SPEAKER_NAME` is set but stereo mode is `mixdown`, surface a one-time hint
   that deterministic self-labeling requires `dual_path` + a stereo mic/system capture
   (i.e. `AUDIO_CHANNELS=2`, mic on one channel, system loopback on the other).
4. Docs: note the requirement (faster-whisper provider, `dual_path`, stereo capture) and how
   it composes with the offline WhisperX/pyannote finalize (which can still relabel the
   `REMOTE` side into individual speakers later).

**Notes / open questions:**

- Depends on a working stereo capture where L=mic and R=system (see the Audio-sources menu:
  pick a mic device and a system/loopback device). If both legs are the same device, the
  channels aren't separable and the guarantee doesn't hold.
- Existing `speaker_aliases` / session-speaker rename already lets a user rename `YOU`
  after the fact; this story makes it automatic and stable from the first segment.
