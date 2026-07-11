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
task arch:check   # check the hexagonal boundary contracts (import-linter; fails on violations)
```

All three import contracts (`domain-independence`, `application-independent-of-adapters`,
`adapters-do-not-import-upward`) are **blocking** since A9: a violation fails `task check`
(via `tests/architecture/`), `task arch:check`, and CI. Depend on the ports in
`domain/ports.py`; only `application/container.py` may import concrete adapters. See
[`architecture-guardrails.md`](architecture-guardrails.md) for the ruleset and history.

### Pre-commit hooks

Pre-commit mirrors the `task check` gates (story C2) so drift is caught before push:

```bash
uv run pre-commit install   # installs BOTH hook stages (pre-commit + pre-push)
```

| Stage | Hooks | Cost |
|-------|-------|------|
| `pre-commit` (every commit) | `ruff format`, `ruff check --fix`, `mypy .` (whole tree, same strictness as `task check`), `lint-imports` (architecture contracts) | ~3 s warm (~20 s the first time while mypy builds its cache) |
| `pre-push` | `pytest -m "not integration"` with the coverage floor — identical to the `task check` test gate | ~70 s |

The pytest gate at `pre-push` (not per-commit) is the one deliberate subset decision — the
tools and strictness are otherwise identical to `task check`. Hooks run via `uv run` on the
project venv, so tool versions always match the `dev` extra instead of separately pinned
pre-commit mirror repos. The parity itself is guarded by
`tests/unit/test_precommit_parity.py`.

### Running locally

```bash
task devices
task run
task tui
```

### Test markers

- **Default:** `uv run pytest` runs unit + e2e + the (ffmpeg-gated) integration lane; `task check` and `task test:unit` use `-m "not integration"` to stay ffmpeg-free.
- **Integration:** deterministic — network boundaries are mocked and fixtures committed, so there is **no** env gate; the tests need **ffmpeg** and are skipped if it's absent. Run with:

```bash
task test:integration    # installs ffmpeg prereqs, then `pytest -m integration`
```

- **E2e smoke:** `tests/e2e/` — CLI contract tests with mocked audio/STT and temp SQLite; no live Teams/mic. Video modules (`transcribe-video`, slides, cleanup) use ffmpeg on a per-run synthetic MP4. Run: `task test:e2e` or `uv run pytest tests/e2e -q`. Fixture mapping: [`docs/test-fixtures.md`](test-fixtures.md#e2e-tests-testse2e).
- **Video integration:** `tests/integration/test_video_import_download.py` mocks the download seam and imports a **committed fixture** presentation (`tests/fixtures/video/`), exercising the real slide/ASR/persistence pipeline with no network.
- **Sample media:** meeting WAVs and presentation MP4s — see [`docs/test-fixtures.md`](test-fixtures.md).

### Test pyramid policy

Notetaker targets an enterprise-grade test pyramid: broad, fast unit tests at the base,
a thin deterministic integration seam layer, and a small set of high-value e2e workflows.
This section is the **policy of record** — the [pyramid drift-guard test](../tests/unit/test_test_pyramid_policy.py)
enforces the machine-checkable parts so the shape can't silently rot.

#### Layer contracts

| Layer | Location | Contract | Must assert |
| --- | --- | --- | --- |
| **Unit** | `tests/unit/`, `tests/architecture/` | Deterministic, fast, no network/GPU/model download. Depend on ports, not providers. Exercise branch logic depth. | Return values, state transitions, error paths |
| **Integration** | `tests/integration/` (`@pytest.mark.integration`) | Adapter seams against filesystem/process/network **fakes** — no live internet. Deterministic; ffmpeg-gated (skipped if absent), no env gate. | Seam behaviour (files written, processes invoked, rows persisted) |
| **E2E** | `tests/e2e/` | CLI → application container → SQLite with mocked audio/STT + temp DB. Small in number, high in value. | **Data-state outcomes** (DB rows, WAV/files written or removed, `ended_at` set) — *not* exit codes alone |

**E2E depth rule:** a critical-workflow e2e (`record`, `finalize`, `cleanup`, video import)
must assert a *persisted outcome*, not just `exit_code == 0`. Exit-code-only e2e tests are
smoke coverage, acceptable only alongside a state assertion.

#### Target ratios (aspirational) vs current reality

Target (from the 2026-07-08 test-pyramid audit):

- Unit: **75–85 %** of test files
- Integration: **10–15 %**
- E2E: **5–10 %** (keep the count small, the value high)

Current reality: **unit ≈ 91 %, e2e ≈ 7 %, integration ≈ 1 %** — the base is over-weight
because the integration lane is still dormant (one network-bound test). Growing the
integration layer toward 10–15 % — a deterministic, CI-executed seam lane — is the next
phase of this program (engineering-backlog stories C3 and T5 Phase 2). Until then the
drift-guard enforces only the regression-proof invariants below, not the aspirational band.

#### Enforced invariants (drift-guard)

The drift-guard fails CI if any of these break — they lock in the current shape and ratchet:

- **Unit dominates** — unit files are ≥ 75 % of all test files (guards against pyramid inversion).
- **E2E stays small** — e2e files are ≤ 15 % of all test files (keeps the slow layer lean).
- **Integration lane survives** — at least one integration test exists (its buildout is Phase 2; deleting it is a regression).

#### Coverage governance

`pytest-cov` with `[tool.coverage.report] fail_under` (currently **65**), enforced by both
`task check` and CI's `test` job. The target is **90 %**, approached **incrementally**: the
floor only ever ratchets **up** as tests land (never down). See the OQ-1 note in `pyproject.toml`.
Per-package / risk-tier floors are a future refinement (needs a coverage plugin; tracked under T2).

#### Skip / xfail governance

Every `skip`/`skipif`/`xfail`/`importorskip` must carry a `reason=` that states **why** and,
where the skip is environmental (ffmpeg, `HF_TOKEN`, GPU), what unblocks it. Skips are for
*missing capability*, never for *known-failing behaviour* — a persistently failing test is
either fixed or quarantined (below), not silently skipped. Review the skip inventory each audit
(`task` note) and delete any whose reason no longer holds. (Tracked: T3.)

#### Flaky-test policy

- A test that fails non-deterministically is **quarantined immediately** — mark it
  `@pytest.mark.flaky` (or `skip` with an explicit `reason="flaky: <issue>"`) so it stops
  blocking merges, and file a story the same day.
- **Retry budget: zero in CI.** CI does not auto-retry; a green run means green on the first
  attempt. Masking flakiness with retries erodes trust in the suite.
- **Stabilisation SLO:** a quarantined test is fixed or deleted within one working week. A skip
  that outlives its story is a governance failure, caught at audit time.

#### Quality SLOs (documented targets)

| Signal | Target | Enforced today |
| --- | --- | --- |
| Coverage floor | ≥ 65 %, ratcheting to 90 % | ✅ `task check` + CI |
| Pyramid shape | unit ≥ 75 %, e2e ≤ 15 %, integration ≥ 1 | ✅ drift-guard |
| Critical e2e depth | asserts persisted state | ⚠️ policy + review (record/finalize/cleanup hardened) |
| Integration lane in CI | deterministic, CI-executed | ❌ Phase 2 / C3 |
| Flaky quarantine turnaround | ≤ 1 week | ❌ process (no dashboard yet) |

### Optional offline diarization (pyannote / WhisperX)

Unit tests **do not** download models. For local manual testing:

1. `uv python pin 3.13` (or 3.12) if needed, then `uv sync --extra whisperx`
2. Create a Hugging Face token and accept the licenses for `pyannote/speaker-diarization-3.1` (and dependencies listed on the model card).
3. Set `HF_TOKEN=...` in `.env`; record a session, then `uv run live-transcriber finalize --session-id <id>`.
4. Map speaker keys: `live-transcriber speaker-alias --session-id <id> --speaker speaker_1 --name "..."`.
