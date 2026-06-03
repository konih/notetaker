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

### Test markers

- **Default:** `uv run pytest` runs unit + e2e smoke tests; skips `@pytest.mark.integration`.
- **Integration:** marked in `pyproject.toml` as `integration: integration tests (skipped unless RUN_INTEGRATION_TESTS=1)`. Enable with:

```bash
RUN_INTEGRATION_TESTS=1 task test:integration
```

- **E2e smoke:** `tests/e2e/` — CLI contract tests with mocked audio/STT (no ffmpeg/GPU). Run: `uv run pytest tests/e2e -q`.

### Optional offline diarization (pyannote / WhisperX)

Unit tests **do not** download models. For local manual testing:

1. `uv python pin 3.13` (or 3.12) if needed, then `uv sync --extra whisperx`
2. Create a Hugging Face token and accept the licenses for `pyannote/speaker-diarization-3.1` (and dependencies listed on the model card).
3. Set `HF_TOKEN=...` in `.env`; record a session, then `uv run live-transcriber finalize --session-id <id>`.
4. Map speaker keys: `live-transcriber speaker-alias --session-id <id> --speaker speaker_1 --name "..."`.
