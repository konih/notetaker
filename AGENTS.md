# AGENTS.md

Guidance for humans and coding agents working on **Notetaker** (`live-meeting-transcriber`): local, Linux-first meeting transcription with chunked capture, SQLite persistence, optional offline speaker attribution, and a Textual TUI.

## Project context

- **Goal:** Capture system audio (PipeWire/PulseAudio monitor, optional mic mix), transcribe in chunks, store timestamped segments locally, summarize via LLM, optional speaker diarization after the session.
- **Stack:** Python 3.12+, `uv`, Typer CLI, Textual TUI, ffmpeg/pactl, SQLite, provider ports (OpenAI / faster-whisper / WhisperX offline).
- **Privacy:** Transcripts stay local in SQLite; cloud APIs only when configured (OpenAI transcription/summaries). See `README.md` for provider matrix.

## Architecture

Follow **clean / hexagonal** boundaries — do not leak provider code into application or domain layers.

- **Read first:** [`docs/architecture.md`](docs/architecture.md)
- **Domain:** `live_meeting_transcriber/domain` — models, events, ports
- **Application:** `live_meeting_transcriber/application` — recorder, finalize, session services
- **Adapters:** `audio/`, `transcription/`, `summarization/`, `diarization/`, `storage/`, `offline/`, `ui/`

**Enforced by import-linter** ([`.importlinter`](.importlinter), memo in
[`docs/architecture-guardrails.md`](docs/architecture-guardrails.md)): the `domain-independence`
contract is blocking (runs in `task check` / CI). The application/adapter contracts are a
report-only pilot — `task arch:check` prints them without failing. Do not add new violations; new
`application → adapter` or `adapter → application` imports are the debt being paid down (story A9).

## Development workflow

```bash
task install          # uv sync --all-extras
task check            # ruff format --check, ruff check, mypy, pytest (unit only)
uv run pytest -q      # all tests; integration skipped by default
uv run ruff check .   # lint
uv run ruff format .  # format
```

- **Unit tests (default):** `uv run pytest` or `task test:unit` (`-m "not integration"`).
- **Integration tests:** `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration` or `task test:integration`.
- **CI parity:** `task check` runs the same pytest + Ruff gates as GitHub Actions, plus a clean mypy typecheck (mypy is green locally; wiring it into CI is tracked separately).

### Python version and optional extras

- Core app: **Python 3.12+** (`requires-python = ">=3.12"`).
- Extras **`whisperx`** and **`diarization`** depend on **PyTorch**, which (as of early 2026) ships wheels only through **CPython 3.13**. On **3.14+**, those extras are omitted from sync.
- For offline `finalize` or pyannote: `uv python pin 3.13` (or 3.12), then `uv sync --extra whisperx` and/or `--extra diarization`.

### Key environment variables

The primary settings store is now `config.yaml` (U21); environment variables and `.env`
remain as overrides/fallback. Precedence: **env var > `config.yaml` > `.env` > default**.
Secrets (`OPENAI_API_KEY`, `HF_TOKEN`) stay env/`.env`-only and are never written to YAML.
See [`docs/configuration.md`](docs/configuration.md).

| Area | Variables |
|------|-----------|
| APIs | `OPENAI_API_KEY`, `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL`, `FASTER_WHISPER_*` |
| Storage | `DATABASE_URL` |
| Audio | `AUDIO_CHUNK_SECONDS`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, `AUDIO_STEREO_MODE`, `AUDIO_INCLUDE_MICROPHONE`, `AUDIO_MACOS_SYSTEM_CAPTURE` |
| Offline speakers | `HF_TOKEN`, `WHISPERX_*`, `FINALIZE_ON_SESSION_STOP` |
| Video / slides | `VIDEO_SLIDE_STRATEGY`, `VIDEO_SLIDE_SAMPLE_INTERVAL_SECONDS`, `VIDEO_SLIDE_CHANGE_THRESHOLD`, `VIDEO_SLIDE_MIN_INTERVAL_SECONDS`, `VIDEO_SLIDE_MAX_CANDIDATES` |
| Legacy / UI flags | `DIARIZATION_ENABLED`, `DIARIZATION_PROVIDER` (do **not** enable live per-chunk pyannote — see configuration doc) |
| Logging | `LOG_LEVEL`, `LOG_ENABLE_FILE`, `LOG_FILE` |

## Commit messages

Use **[Conventional Commits](https://www.conventionalcommits.org/)** only — **no JIRA/ticket IDs**, no required gitmoji.

```
<type>[optional scope]: <short summary>

[optional body]
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.

Examples:

- `docs: correct diarization paths in configuration`
- `test: add CLI record smoke e2e skeleton`
- `fix(recorder): drain chunk on stop`

### Atomic commits

- **One logical change per commit** when possible (reviewable, bisect-friendly).
- Group related doc + test updates if they ship one feature; split unrelated concerns.
- Do **not** update git config. Do **not** force-push `main`/`master`.

### Agents may commit and push

When work is complete and tests pass, agents may **commit** (conventional messages) and **`git push`** to the current branch unless the user says otherwise. If push fails (no remote, auth), commit locally and report clearly.

## Multitask / coordinator mode

When several agents run in parallel (e.g. Cursor multitask):

| Workstream | Typical scope | Merge order |
|------------|---------------|-------------|
| **Docs** | `README.md`, `docs/*`, `AGENTS.md`, `.env.example` | Early — unblocks others |
| **Code** | `live_meeting_transcriber/**` | After docs if env/behavior changed |
| **Tests** | `tests/**` | After or with code; keep green |

**Avoid duplicate edits:** assign non-overlapping files per agent. If two agents must touch the same module, serialize merges or split by function (one agent implements, one adds tests).

**Commits:** Prefer **one conventional commit per logical change**; or a small numbered series (`docs: …`, then `feat: …`, then `test: …`). Do not squash unrelated parallel work into one blob.

**Coordinator checklist:** assign paths → run `task check` after merge → resolve conflicts in shared modules (`settings.py`, `container.py`, `cli/main.py`) carefully → single push per integrated branch.

## Git Reviewer (audit gate)

Optional **Git Reviewer** role before commit or PR: quality gates and commit hygiene, **not** feature implementation.

### Git Reviewer responsibilities

**Quality gates** (all must pass before push):

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv run pytest tests/e2e -q    # when video/ffmpeg touched
task check                    # before final push
```

**Git review:** inspect `git status`, `git diff`, and `git log`; enforce atomic commits, Conventional Commits (no ticket IDs), no secrets, no large binaries unless explicitly approved, no mixed concerns.

**Propose:** commit grouping and subjects; flag files that must **not** be committed.

**Does not:** implement features, force-push, amend without the rules in [Commit messages](#commit-messages), or update git config.

Before commit or PR: run the gate suite above; enforce atomic Conventional Commits; exclude secrets, `.pyc`, and oversized media. For video/ffmpeg changes, also run `uv run pytest tests/e2e -q` (CI e2e job installs ffmpeg via `task install:video-prereqs`).

### NFR audit checklist

Verify on every PR that touches user-facing behavior (especially video, cleanup, export, or logging):

| NFR | Gate |
|-----|------|
| **Privacy** | No transcript text in logs, tests, or commit messages; cleanup output is paths/counts only |
| **Safety** | Destructive CLI defaults to dry-run; deletion requires `--yes` or `--no-dry-run` |
| **Performance** | Slide preview re-runs detection only (no re-transcribe) |
| **Maintainability** | Slide strategies live under `video/strategies/`; application orchestrates via ports |
| **Testability** | New CLI paths have e2e smoke; strategies have unit tests on fixture MP4 |
| **CI parity** | Video/ffmpeg changes pass `uv run pytest tests/e2e -q` (CI installs ffmpeg via `task install:video-prereqs`) |

Also check commit hygiene (one logical change per commit, bisect-friendly order) and that parallel workstreams did not collide on the same hot files (`settings.py`, `container.py`, `cli/main.py`).

### When to invoke

- Before **PR creation**
- When the user asks an agent to **commit**

## Deferred / future work

**Not implemented — do not start without explicit user request:**

- **Microsoft Graph / delegated OAuth** calendar import (Teams meeting metadata, auto-titles). Note in roadmap/docs only; no OAuth code in this repo yet.

## End-to-end (E2E) testing

### What “e2e” means here

End-to-end means exercising the **CLI → application container → SQLite** path with realistic orchestration, **without** requiring a live Teams call or GPU every CI run. Real microphone/Teams audio is **optional** and belongs in manual checklists.

### Layered strategy

1. **Contract / smoke e2e (CI-friendly)**  
   Subprocess or Typer `CliRunner` against `live_meeting_transcriber.cli.main:app` with:
   - Temp `DATABASE_URL` (SQLite under `tmp_path`)
   - **Mocked** `Recorder`, ffmpeg capture, and cloud/local STT (or real ffmpeg on a locally generated sample MP4 for video paths)
   - **No live Teams/mic** — local fixtures and generated media only; see [`docs/test-fixtures.md`](docs/test-fixtures.md#e2e-tests-testse2e)
   - Assert exit code, session row, transcript line  
   - First target: `tests/e2e/test_cli_record_smoke.py`

2. **Integration tests (`@pytest.mark.integration`)**  
   Skipped unless `RUN_INTEGRATION_TESTS=1` (see `tests/conftest.py`).  
   Tiny fixture WAV, optional real faster-whisper or WhisperX; skip heavy steps when `HF_TOKEN` unset. Keep runtime short.  
   Sample meeting audio and presentation videos: [`docs/test-fixtures.md`](docs/test-fixtures.md) (`task fixtures:fetch`).

3. **Manual e2e (Ubuntu / Teams)**  
   Human checklist: `pactl list short sources` → `live-transcriber record` ~30s → stop → `finalize` (if whisperx extra) → export markdown; verify speaker aliases.

### How agents should run tests

| Intent | Command |
|--------|---------|
| Default / PR | `uv run pytest -q` or `task check` |
| Unit only | `uv run pytest -m "not integration"` |
| Integration | `RUN_INTEGRATION_TESTS=1 uv run pytest -m integration` |
| E2e smoke | `uv run pytest tests/e2e -q` |

Add new e2e tests under `tests/e2e/`; prefer mocks over network/GPU. Do not call OpenAI in CI without explicit opt-in.

## Diarization (agent quick reference)

- **Live recording:** Chunk transcription only; **no** per-chunk pyannote in the recorder. Speaker hints during live capture come from **`AUDIO_STEREO_MODE=dual_path`** + `faster_whisper` (mic vs system channels), not from `DIARIZATION_ENABLED`.
- **Offline:** `live-transcriber finalize` runs WhisperX + pyannote on `full_session.wav` (needs `whisperx` extra, `HF_TOKEN`).
- **Legacy:** `application/diarization_batch.py` can reprocess stored chunk WAVs but there is **no** `live-transcriber diarize` CLI command.

## Code style (Python)

- Ruff lint + format (`pyproject.toml`); line length 100, target 3.12.
- Strict typing in new code; match existing patterns in touched files.
- Minimize scope — no drive-by refactors unrelated to the task.

## References

- [`README.md`](README.md) — install, CLI, models
- [`docs/configuration.md`](docs/configuration.md) — env vars
- [`docs/development.md`](docs/development.md) — local setup, integration marker
- [`docs/test-fixtures.md`](docs/test-fixtures.md) — sample meeting WAVs and presentation MP4s
- [`docs/roadmap.md`](docs/roadmap.md)
