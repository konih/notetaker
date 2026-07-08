## Development

### Requirements

- Python 3.12+
- `uv`
- Linux packages:
  - `pulseaudio-utils` (for `pactl`)
  - `ffmpeg`
- **Video import** (`transcribe-video`): `ffmpeg` + `yt-dlp`. Install with:

```bash
task install:video-prereqs
```


### Install

```bash
task install
```

### Quality checks

```bash
task check        # ruff format check + ruff + mypy + unit tests (incl. the arch guard)
task arch:check   # report hexagonal boundary violations (import-linter pilot; never fails)
```

`task check` enforces the `domain-independence` import contract (the domain layer must not import
outer layers). `task arch:check` prints the full boundary report — including the currently-broken
application/adapter contracts — without failing, so known debt does not block work. See
[`architecture-guardrails.md`](architecture-guardrails.md) for the ruleset and rollout plan.

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

- **E2e smoke:** `tests/e2e/` — CLI contract tests with mocked audio/STT and temp SQLite; no live Teams/mic. Video modules (`transcribe-video`, slides, cleanup) use ffmpeg on a per-run synthetic MP4. Run: `task test:e2e` or `uv run pytest tests/e2e -q`. Fixture mapping: [`docs/test-fixtures.md`](test-fixtures.md#e2e-tests-testse2e).
- **Video integration:** `tests/integration/test_video_import_download.py` imports an English presentation YouTube URL when `RUN_INTEGRATION_TESTS=1`. Prepare committed clips with `task fixtures:fetch`.
- **Sample media:** meeting WAVs and presentation MP4s — see [`docs/test-fixtures.md`](test-fixtures.md).

### Optional offline diarization (pyannote / WhisperX)

Unit tests **do not** download models. For local manual testing:

1. `uv python pin 3.13` (or 3.12) if needed, then `uv sync --extra whisperx`
2. Create a Hugging Face token and accept the licenses for `pyannote/speaker-diarization-3.1` (and dependencies listed on the model card).
3. Set `HF_TOKEN=...` in `.env`; record a session, then `uv run live-transcriber finalize --session-id <id>`.
4. Map speaker keys: `live-transcriber speaker-alias --session-id <id> --speaker speaker_1 --name "..."`.
