## Development

### Requirements

- Python 3.12+
- `uv`
- Linux packages:
  - `pulseaudio-utils` (for `pactl`)
  - `ffmpeg`

### Install

```bash
task install
```

### Quality checks

```bash
task check
```

### Running locally

```bash
task devices
task run
task tui
```

### Integration tests

Integration tests are skipped unless explicitly enabled:

```bash
RUN_INTEGRATION_TESTS=1 task test:integration
```

### Optional diarization (pyannote)

Unit tests **do not** download models. For local manual testing:

1. `uv sync --extra diarization`
2. Create a Hugging Face token and accept the licenses for `pyannote/speaker-diarization-3.1` (and dependencies listed on the model card).
3. Set `DIARIZATION_ENABLED=true`, `DIARIZATION_PROVIDER=pyannote`, and `HF_TOKEN=...` in `.env`.
4. Consider `KEEP_AUDIO_CHUNKS=true` if you plan to run `live-transcriber diarize` later on stored WAVs.
