# Architecture guardrails — decision memo (story A10)

Status: **pilot / report-only** · Introduced: 2026-07-08 · Follow-up: story **A9** (promote to blocking)

Notetaker follows a clean/hexagonal architecture (see [`architecture.md`](architecture.md)).
Until now that boundary was enforced only by review. This memo records the decision to adopt
an automated import-boundary guardrail, the pilot ruleset, the current violation inventory, and
the phased plan to make it blocking.

## Decision: Import Linter

**Selected tool: [Import Linter](https://import-linter.readthedocs.io/)** (`import-linter`, pinned
in the `dev` extra), driven by contracts in [`.importlinter`](../.importlinter).

Rationale:

| Candidate | Verdict | Notes |
| --- | --- | --- |
| **Import Linter** | ✅ **chosen** | Declarative contracts (`forbidden`, `layers`, `independence`); pure-Python; built on `grimp`'s import graph; per-contract selection (`--contract`) lets us enforce one contract while others stay report-only; in-process API (`importlinter.cli.lint_imports`) makes it trivial to gate from pytest. No runtime dependency — dev-only. |
| `grimp` + custom checks | ➖ rejected for now | Import Linter *is* the ergonomic layer over `grimp`; hand-rolling contract logic duplicates it with no upside for a pilot. Still the escape hatch if we need a bespoke rule Import Linter can't express. |
| Ruff path/import constraints (`flake8-tidy-imports` `banned-api`, `TID`) | ➖ complementary, not sufficient | Ruff can ban specific import paths per file, but it reasons per-module, not over the whole import graph, so it can't express layered/transitive contracts. Fine as a cheap secondary guard later. |

## Pilot ruleset

`root_package = live_meeting_transcriber`. Three contracts:

| Contract id | Type | Enforcement | Today |
| --- | --- | --- | --- |
| `domain-independence` | forbidden | **BLOCKING** (pytest + `task check` + CI unit job) | ✅ KEPT |
| `application-independent-of-adapters` | forbidden | report-only (`task arch:check`, non-blocking CI `arch` job) | ❌ BROKEN |
| `adapters-do-not-import-upward` | forbidden | report-only | ❌ BROKEN |

- **Blocking** is scoped to the single invariant that already holds — the domain layer imports
  nothing outward. It is gated in [`tests/architecture/test_import_contracts.py`](../tests/architecture/test_import_contracts.py)
  (via `--contract domain-independence`), so a regression fails `task check` and the CI unit job.
- **Report-only** contracts document real debt without blocking merges. Run them with
  `task arch:check` (never fails) or read the non-blocking CI `arch` job.
- The composition root `application/container.py` is *exempt* from the application contract
  (`ignore_imports = ...container -> live_meeting_transcriber.**`): wiring concrete adapters is
  its job.

## Violation inventory (2026-07-08)

Analyzed 101 files / 238 dependencies. Two report-only contracts broken.

### Batch 1 — application → concrete adapters (owner: A-epic)

`application` should depend on `domain` + ports only. Concrete-adapter imports found (container
excluded):

| Module | Imports | Fix path |
| --- | --- | --- |
| `application/finalize_service.py` | `offline.whisperx_pipeline` | Introduce an offline-ASR **port**; inject the WhisperX impl via container. → new story / **A4** neighbourhood |
| `application/slide_preview_service.py` | `video.slide_common`, `video.strategies.factory` | Depend on the `SlideDetectionStrategy` port + a factory port; inject concrete strategies. |
| `application/video_import_service.py` | `video.slide_common`, `video.strategies.factory`, `audio.*` | Same as above + audio helpers behind ports. |
| `application/recorder.py` | `audio.session_recording/stereo/timeline/wav_*` | **A4** — extract an audio-IO port for WAV/timeline append. |
| `application/screenshot_export.py`, `session_media.py`, `video_session_storage.py` | `audio.session_recording` | Small: move `session_audio_dir`/path helpers behind a storage-path port or into domain. |
| `application/session_service.py` | `obsidian.vault_patterns` | Move `is_placeholder_meeting_title` into domain (pure predicate). |
| `application/diarization_batch.py` | `diarization.merge_service` | Dead per **A7** — resolve there (remove or wire), don't refactor speculatively. |

### Batch 2 — adapter → application (owner: A-epic)

| Module | Imports | Fix path |
| --- | --- | --- |
| `obsidian/meeting_export.py` | `application.export_markdown` / `export_overwrite` / `screenshot_export` | Upward leak. Move shared export helpers down to `domain`/a shared util, or invert so `application` orchestrates `obsidian`. New story under the A epic. |

`domain` (✅ clean) and `storage` (✅ leaf, no sibling/upward imports) need no work.

## Rollout / phased adoption gates

1. **Phase 0 — pilot (this story, done):** tool wired; `domain-independence` blocking; other
   contracts report-only in `task arch:check` + non-blocking CI.
2. **Phase 1 — stop the bleeding:** keep report-only, but treat *new* violations as review
   blockers. Entry criteria for promoting a contract to blocking: its violation count is **0**.
3. **Phase 2 — pay down Batch 1/2** via the A-epic refactors (ports for offline/video/audio;
   relocate `obsidian`→`application` leak). As each contract reaches 0 violations, move its id
   into `ENFORCED_CONTRACTS` in the guard test and delete it from the report-only set.
4. **Phase 3 — fully enforced (story A9):** all three contracts blocking; drop `continue-on-error`
   from the CI `arch` job; consider a `layers` contract for the full hexagon.

### Follow-up: story A9 entry criteria

Promote `application-independent-of-adapters` and `adapters-do-not-import-upward` to blocking when:

- Batch 1 and Batch 2 violation counts are both 0 (verified by `task arch:check`), **and**
- the relevant A-epic ports exist (offline-ASR, slide-detection, audio-IO), **and**
- `ENFORCED_CONTRACTS` in the guard test has been widened to include them with a green suite.

## How to run

```bash
task arch:check                       # full report, never fails (pilot)
uv run lint-imports                   # same report
uv run lint-imports --contract domain-independence   # the blocking subset
uv run pytest tests/architecture      # the guard test that gates task check
```
