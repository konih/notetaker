# ADR 0001: Stop silently dropping diarization when the app exits

Status: Accepted (2026-07-09)

## Problem

"Diarization doesn't work." Verified against a copy of a real user database:
**0 of 31** recorded sessions had ever completed offline finalize (WhisperX +
diarization), despite `FINALIZE_ON_SESSION_STOP=true`. Every transcript segment
was still `"unknown"`.

The offline finalize itself (`finalize_session_offline` over the whole
`full_session.wav`) works correctly. The defect was in how it was scheduled:

- `TuiController`'s `RecordingStopRequested` handler fired the multi-minute
  finalize via a bare `asyncio.create_task(...)  # noqa: RUF006` with **no
  reference stored anywhere**. The event loop keeps only a weak reference, so
  the task is eligible for garbage collection — and `action_quit` calls
  `self.exit()` immediately after dispatching the stop action. A completely
  normal "stop recording, then close the app" flow killed the job before
  WhisperX finished.
- The manual "Speaker ID" trigger (`FinalizeSessionRequested`) took the
  opposite bad path: it `await`ed the whole pass inline in `handle()`, which is
  itself awaited from Textual's key-binding dispatch — freezing the UI for the
  duration.

## Decision

Route **every** finalize trigger through a tracked, sequential background queue
on `TuiController` (`_enqueue_finalize` → `_finalize_worker` /
`_finalize_worker_task`):

1. Jobs run one at a time (avoids GPU/CPU contention) and the worker task is
   held on the controller, so it is not GC'd out from under the loop.
2. **Startup recovery** (safety net): on `AppStarted`, scan for sessions ended
   in the last 24h whose transcript is non-empty and entirely `"unknown"`
   (`find_unfinalized_sessions`) and re-enqueue them. Bounded to 24h and gated
   on `hf_token` so it is not a surprise multi-hour GPU sweep of the whole
   history on every launch, and not an infinite retry for a session that
   legitimately has no diarization credentials. This catches anything the
   event-loop teardown still drops on a quick quit.
3. **CLI backfill**: `live-transcriber finalize-pending [--dry-run]` runs the
   same query with no time bound, so a user can deliberately re-diarize their
   existing backlog of orphaned sessions on their own schedule.

### Consequences

- Any future caller of `_run_finalize_for_session` must go through
  `_enqueue_finalize` — calling it inline re-introduces the UI-freeze bug, and a
  bare `create_task` re-introduces the silent-drop bug.
- `find_unfinalized_sessions` normalises naive/aware `ended_at` to UTC before
  the recovery-window comparison, since a pre-existing DB can mix naive (old)
  and tz-aware (post-A1) rows (roadmap **A11**).
- No schema changes, no new required settings.

### Rejected alternatives

- **Awaiting the finalize task before `self.exit()` on quit** — trades the
  silent-drop bug for a hang-on-quit bug (WhisperX on a long meeting can take
  10–30 minutes). Survive-exit-without-blocking (queue + startup recovery) was
  chosen instead.
- **Live per-chunk diarization** — pyannote clusters speakers fresh per call
  with no memory across short chunks, so it reproduces the complaint in a
  noisier form. Not pursued.

## Provenance / scope

Salvaged from the stale `worktree-live-tab-diarization` branch (2026-07-02).
Deliberately **not** carried over:

- Its inline Live-tab title/notes/attendees editing — already shipped as **U20**
  (main's version has the speaker-alias machinery this branch lacked).
- Its `BusyOperationStarted/Progress/Finished` + `LoadingIndicator` spinner UI —
  the render was entangled with the discarded editing work on a since-diverged
  `app.py`. Textual status feedback still flows through the existing
  `UiLogLineAdded` dispatches; a dedicated spinner is a possible follow-up.
