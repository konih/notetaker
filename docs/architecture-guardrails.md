# Architecture guardrails — decision memo (stories A10 + A9)

Status: **ENFORCED (all three contracts blocking)** · Pilot introduced: 2026-07-08 (A10) · Promoted to blocking: 2026-07-11 (A9, per operator decision OQ-3)

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
| `domain-independence` | forbidden | **BLOCKING** (pytest + `task check` + CI unit job + CI `arch` job) | ✅ KEPT |
| `application-independent-of-adapters` | forbidden | **BLOCKING** (same) | ✅ KEPT |
| `adapters-do-not-import-upward` | forbidden | **BLOCKING** (same) | ✅ KEPT |

- All three contracts are gated in [`tests/architecture/test_import_contracts.py`](../tests/architecture/test_import_contracts.py)
  (`ENFORCED_CONTRACTS`), so a regression fails `task check` and the CI unit job; the CI `arch`
  job and `task arch:check` run the same `lint-imports` check and are blocking too.
- The composition root `application/container.py` is *exempt* from the application contract
  (`ignore_imports = ...container -> live_meeting_transcriber.**`): wiring concrete adapters is
  its job. Do not add further `ignore_imports`; invert new dependencies through ports.

## Violation inventory (2026-07-08) — cleared by A9 (2026-07-11)

Original pilot inventory (101 files / 238 dependencies, two contracts broken), kept for
history. **All edges below are fixed**; the "Fix path" column records what actually landed.

### Batch 1 — application → concrete adapters (owner: A-epic)

`application` should depend on `domain` + ports only. Concrete-adapter imports found (container
excluded):

| Module | Imported | Fix that landed (A9) |
| --- | --- | --- |
| `application/finalize_service.py` | `offline.whisperx_pipeline`, `audio.session_recording/timeline` | `OfflineTranscriber` port (impl `WhisperxOfflineTranscriber`, lazily built by `Container.offline_transcriber()`); timeline reads via `SessionAudioStore`; paths from `domain.session_audio`. |
| `application/slide_preview_service.py` | `video.slide_common`, `video.strategies.factory`, `audio.media_import` | `SlideDetectionTools` + `MediaImporter` ports (impls `FfmpegSlideDetectionTools`, `FfmpegMediaImporter`), wired by the container. |
| `application/video_import_service.py` | `video.*`, `audio.*` | Same ports plus `WavAudioOps` (`FfmpegWavOps`) and `SessionAudioStore` (`FfmpegSessionAudioStore`). |
| `application/recorder.py` | `audio.session_recording/stereo/wav_level` | `SessionAudioStore` (chunk+timeline append) and `WavAudioOps` (levels, channel split, mixdown) ports. |
| `application/screenshot_export.py`, `session_media.py`, `video_session_storage.py` | `audio.session_recording` | Path layout moved to `domain/session_audio.py` (`session_audio_dir`, `full_session_wav_path`). |
| `application/session_service.py` | `obsidian.vault_patterns` | `is_placeholder_meeting_title` moved to `domain/meeting_naming.py` (pure predicate). |
| `application/export_markdown.py` | `obsidian.meeting_export` | `ExportCancelledError` moved to `domain.exceptions`; `slug_title` to `domain/meeting_naming.py`. |

### Batch 2 — adapter → application (owner: A-epic)

| Module | Imported | Fix that landed (A9) |
| --- | --- | --- |
| `obsidian/meeting_export.py` | `application.export_markdown` / `export_overwrite` / `screenshot_export` | Inverted: `prepare/write_dual_export` moved to `application/dual_export.py`; the adapter keeps rendering/naming only and implements the `MeetingNoteRenderer` port (`ObsidianMeetingNoteRenderer`). |

`domain` (✅ clean) and `storage` (✅ leaf, no sibling/upward imports) need no work.

## Rollout / phased adoption gates

1. **Phase 0 — pilot (A10, done 2026-07-08):** tool wired; `domain-independence` blocking; other
   contracts report-only in `task arch:check` + non-blocking CI.
2. **Phase 1 — stop the bleeding (done):** new violations treated as review blockers.
3. **Phase 2 — pay down Batch 1/2 (A9, done 2026-07-11):** ports for offline-ASR
   (`OfflineTranscriber`), media import (`MediaImporter`), WAV ops (`WavAudioOps`),
   session-audio persistence (`SessionAudioStore`), slide detection (`SlideDetectionTools`)
   and vault note rendering (`MeetingNoteRenderer`); pure layout/naming/exception types moved
   into `domain/`.
4. **Phase 3 — fully enforced (A9, done 2026-07-11):** all three contracts blocking;
   `continue-on-error` dropped from the CI `arch` job; `task arch:check` fails on violations.
   Possible future hardening: a `layers` contract for the full hexagon.

### Follow-up: story A9 entry criteria

**DONE (2026-07-11).** All entry criteria were met and the promotion landed:

- Batch 1 and Batch 2 violation counts are both 0 — `task arch:check` reports
  `Contracts: 3 kept, 0 broken`.
- The A-epic ports exist (offline-ASR, slide-detection, media-import, audio-IO,
  session-audio store, meeting-note renderer) and are wired via the container.
- `ENFORCED_CONTRACTS` in [`tests/architecture/test_import_contracts.py`](../tests/architecture/test_import_contracts.py)
  now lists all three contracts, with a green suite.

## How to run

```bash
task arch:check                       # full contract check, fails on violations
uv run lint-imports                   # same check
uv run pytest tests/architecture      # the in-process guard that gates task check
```
