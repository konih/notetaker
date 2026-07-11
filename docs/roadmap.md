## Roadmap

### Recently completed (2026)

Shipped on `main` (see [`docs/configuration.md`](configuration.md) and [`docs/architecture.md`](architecture.md)):

- **Video import** — `transcribe-video` from local file or URL; ffmpeg + optional yt-dlp
- **Slide detection** — pluggable `frame_diff` / `ffmpeg_scene` strategies; env + CLI overrides
- **Preview workflow** — `slides preview` / `slides apply` without re-transcribing
- **Cleanup** — `cleanup` CLI (dry-run default) and TUI session delete share `CleanupService`
- **Offline speakers** — `finalize` (WhisperX + pyannote); live `dual_path` stereo hints with faster-whisper
- **TUI** — session browser, slide preview with parameter tuning
- **Live meeting details** — set title, context/notes, attendees, and name detected speakers for the *current* live meeting from the Live tab (`t`); notes pre-fill the summary context
- **Tests / CI** — e2e smoke for video, slides, cleanup; CI installs ffmpeg for e2e job; enforced coverage floor + a documented [test-pyramid policy](development.md#test-pyramid-policy) with a drift-guard that fails CI on pyramid inversion (T5 Phase 1)

### Phase 1 (current)

- CLI
- audio capture (PipeWire/PulseAudio monitor)
- chunked OpenAI transcription
- SQLite persistence
- Markdown export

### Phase 2

- speaker diarization polish (live record screen capture, richer TUI speaker UX)
- better realtime streaming / incremental transcription
- session search and filtering — shipped: CLI `sessions --search` (F2), Meetings-tab filter with date tokens (U17), fuzzy jump-to-meeting picker (U11)
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

1. Add config `SELF_SPEAKER_NAME` (default unset; the reporter wants `Konrad Heimel`). When
   set, the mic channel in `dual_path` is labeled with that name instead of `YOU`; optionally
   add `REMOTE_SPEAKER_NAME` for the system side (default keep `REMOTE`).
2. Thread the name from `Settings` → `Recorder`/`FasterWhisperTranscriptionProvider` so the
   `speaker=` field on mic segments is the configured name at creation time (no post-hoc
   remap, no diarization pass).
3. UX: when `SELF_SPEAKER_NAME` is set but stereo mode is `mixdown`, surface a one-time hint
   that deterministic self-labeling requires `dual_path` + a stereo mic/system capture
   (i.e. `AUDIO_CHANNELS=2`, mic on one channel, system loopback on the other).
4. Docs: note the requirement (faster-whisper provider, `dual_path`, stereo capture) and how
   it composes with the offline WhisperX/pyannote finalize (which can still relabel the
   `REMOTE` side into individual speakers later).

**Part B — mic voice-activity timeline (independent evidence "this is me"):**

Beyond labeling transcript segments, the reporter also wants a record of *when there was
voice on the mic*, so a segment attributed to `Konrad Heimel` can be corroborated against
actual mic energy (guards against bleed/crosstalk labeling silence as the reporter).

1. Reuse the existing primitives — no new capture infra: `audio/wav_level.py`
   (`peak_linear_from_wav_path`, per-chunk peak/RMS) for voice-activity detection and
   `audio/timeline.py` (`AudioTimelineEntry`, audio-seconds → wall-clock) for mapping.
2. Per chunk (or a finer sub-window of it), compute the **mic-channel** level; when it
   exceeds a configurable threshold, emit a voice-active interval. Persist as a
   `mic_voice_activity.jsonl` alongside `session_audio_timeline.jsonl` (wall-clock spans),
   or as segment metadata on mic segments.
3. Config: `SELF_SPEAKER_VAD_ENABLED` (default off) and `SELF_SPEAKER_VAD_THRESHOLD`
   (0..1 peak, e.g. `0.02`). Keep it a simple energy gate first — "at least keep track";
   full VAD (webrtcvad / silero) is a later refinement.
4. Surface: include the mic-active spans in the export / make them queryable so
   `Konrad Heimel` attributions can be filtered to intervals with real mic energy.

Depends on the same `dual_path` stereo capture as Part A (the mic must be its own channel).

**Notes / open questions:**

- Depends on a working stereo capture where L=mic and R=system (see the Audio-sources menu:
  pick a mic device and a system/loopback device). If both legs are the same device, the
  channels aren't separable and the guarantee doesn't hold.
- Existing `speaker_aliases` / session-speaker rename already lets a user rename `YOU`
  after the fact; this story makes it automatic and stable from the first segment.
- Capturing the remote (Teams) side at all requires a loopback source — see
  [system-audio-capture.md](system-audio-capture.md). Without it there is no `REMOTE`
  channel and Part A/B degrade to mic-only.

### (Optional) Native macOS system-audio capture via ScreenCaptureKit — BlackHole alternative

**Ask:** Capture Teams/system output **without** asking the user to install BlackHole and
build a Multi-Output Device (see [system-audio-capture.md](system-audio-capture.md) for the
current, supported BlackHole flow). This is an **optional convenience** story — the BlackHole
path already works today; this only removes the manual setup on macOS.

**Approach:** Use Apple's **ScreenCaptureKit** (`SCStream` with audio, macOS 13+) or a
**CoreAudio process/aggregate tap** (macOS 14.4+ `AudioHardwareCreateProcessTap`) to read
system output directly, then feed PCM into the existing chunk/transcription pipeline in place
of the ffmpeg loopback `--source`.

**Feasibility / effort (must spike before committing):**

- This is **native work**, not an ffmpeg flag. ffmpeg's `avfoundation` input has **no**
  ScreenCaptureKit audio path, so we cannot get it "for free" from the current capture command.
- Options, cheapest first:
  1. A small **helper binary** (Swift, ScreenCaptureKit) that writes PCM/WAV to stdout or a
     socket; the Python side spawns it much like ffmpeg. Keeps native code isolated and the
     Python pipeline unchanged. **Recommended spike target.**
  2. Python bindings via **PyObjC** to drive `SCStream` directly — no separate binary, but
     ScreenCaptureKit's delegate/callback model is awkward from Python and version-fragile.
  3. Wait for/verify whether a maintained ffmpeg build exposes a ScreenCaptureKit audio
     device (not currently the case).
- **Permissions:** ScreenCaptureKit requires **Screen Recording** permission (TCC) even for
  audio-only capture — a first-run prompt and a packaging/entitlements concern for the
  desktop app. Document this as a hard requirement.
- **OS floor:** macOS 13+ for `SCStream` audio; the CoreAudio process-tap route needs 14.4+.
  Below that, fall back to BlackHole.

**Scope / requirements to document:**

- **macOS:** version floor, Screen Recording (TCC) permission, entitlements for the packaged
  app, and graceful fallback to the BlackHole flow when unavailable.
- **Linux:** **not applicable** — PipeWire/PulseAudio `.monitor` already provides native
  system capture with no extra driver (see [system-audio-capture.md](system-audio-capture.md)).
  This story is macOS-only.

**Decision gate:** run the option-1 Swift-helper spike (capture 10s of system audio to WAV,
confirm it matches what BlackHole captured) before scheduling the full integration. If the
spike is costly or fragile, stay on BlackHole and just improve its setup UX.

### (Optional) First-class YAML config file — replace env-var configuration

**Ask:** Configuring audio (channels, stereo mode, mic/system sources, self-speaker name) via
environment variables is unpleasant. Provide a proper, discoverable **YAML config file**.

**Approach:**

1. Add `~/.config/live-meeting-transcriber/config.yaml` as a `pydantic-settings` source. Keep
   the existing `Settings` model as the single source of truth; add a YAML settings source so
   fields load from YAML **without** renaming/duplicating the schema.
2. **Precedence (highest wins):** explicit CLI flag → environment variable / `.env` →
   `config.yaml` → built-in defaults. Document this order; it keeps current env/CLI setups
   working unchanged (YAML is additive, not a breaking migration).
3. Structure the YAML by area (e.g. `audio:`, `transcription:`, `summarization:`, `logging:`)
   mapping onto the existing flat `AUDIO_*` / `FASTER_WHISPER_*` fields via aliases, so both
   forms address the same settings.
4. Reconcile with `device_prefs.json` (TUI-persisted `monitor_source` / `microphone_source`):
   decide whether YAML supersedes it or they coexist with a clear precedence; document it.
5. CLI: `live-transcriber config init` to write a commented starter file, and
   `config path` / `config show` (effective, merged values) to aid discovery.
6. Docs: convert [configuration.md](configuration.md)'s env-var reference into YAML keys with
   the env equivalents shown alongside, so neither audience is stranded.

**Notes / open questions:**

- Secrets (`OPENAI_API_KEY`, `HF_TOKEN`) should **stay** env-only by convention — don't
  encourage writing them into a checked-in YAML file. Validate/warn if present in YAML.
- Keep it dependency-light: `pydantic-settings` supports a YAML source (or a thin custom
  source) — avoid adding a heavy config framework.
