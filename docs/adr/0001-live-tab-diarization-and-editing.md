# ADR 0001: Fix silently-dropped diarization + inline meeting editing on the Live tab

## Story

Two complaints from live usage:

1. "Diarization doesn't work."
2. Title / notes ("context") / attendees ("participants") can only be edited from
   the Meetings tab. If a meeting is currently recording, there is no way to edit
   these fields from the Live tab — the user has to know to switch tabs, find the
   in-progress row, and edit it there.

## Context

### Diarization: the pipeline works, the background task doesn't survive exit

The initial hypothesis was that speaker labels never appear *during* recording.
That's true but expected (there is no streaming diarization model in the loop,
by design — a prior commit explicitly removed live per-chunk diarization). A
per-chunk pyannote wiring was prototyped and reverted: pyannote clusters
speakers fresh from whatever audio it's given each call, so calling it on
isolated few-second chunks gives it no memory across calls — most chunks
contain one voice and get labelled `speaker_1` regardless of who is talking,
and even when two voices appear in one chunk, the numbering doesn't carry over
to the next chunk. That's not a fix, it reproduces the same complaint in a
noisier form.

The real, verified root cause was found by testing against a copy of the
user's actual database (97 recorded sessions):

- `finalize_session_offline` (offline WhisperX + diarization over the whole
  `full_session.wav`) **works correctly** — verified by running it for real
  (HF_TOKEN + GPU available in this environment) against an actual ~3-minute
  recorded session: it produced stable, correct multi-speaker labels
  (`YOU`, `REMOTE_1`, `REMOTE_2`) for the whole conversation.
- Despite `FINALIZE_ON_SESSION_STOP=true` being configured, **0 of 31** real
  sessions in the user's database had ever been successfully diarized — every
  transcript segment was still `"unknown"` (one stray exception aside).
- The log file confirms why: `ui/effects/controller.py`'s
  `RecordingStopRequested` handler fired the multi-minute finalize job via a
  bare `asyncio.create_task(...)` with **no reference stored anywhere**
  (`# noqa: RUF006` acknowledged the smell but didn't fix it). `action_quit`
  calls `self.exit()` immediately after dispatching the stop action — a
  completely normal "stop recording, close the app" flow. The event loop only
  holds a *weak* reference to an untracked task, so it gets killed before
  WhisperX finishes. Grepping the log for finalize milestones across ~5 weeks
  of real usage: 18 "started transcribing", only 1 real completion (plus 2
  from this investigation's own manual CLI runs) — every other attempt is cut
  off mid-`"Transcribing…"` with no further trace.

### Live tab editing

- Editing title/notes/attendees while a session is recording already works at
  the persistence layer: `MeetingBrowser.action_save_meeting` calls
  `Container.sessions.update_details(...)` directly with no recording-status
  guard, and the `m` → Sessions modal → `e` title-rename path
  (`SessionTitleCommitRequested`) proves mid-recording renames already persist
  and sync back into `AppState.session_title`. The gap is purely that the Live
  tab's widget tree (`app.py` `TabPane("Live", ...)`) had no editable widgets
  at all — three `Static`s and a `RichLog`.
- A theoretical concern that App-level `priority=True` bindings (`w`, `k`,
  `ctrl+i`) might intercept keystrokes typed into the new Live tab fields
  before they reach the focused `Input`/`TextArea` was checked empirically
  with a Textual pilot test *before* writing any fix: it doesn't happen —
  Textual gives the focused widget first claim on printable characters, Tab
  moves focus normally, and `ctrl+i` firing finalize while a field is focused
  is the same intentional behavior as `ctrl+s`. No code change was needed
  there; the pilot test is kept as a regression guard.

## Decision

**Diarization**: don't touch the per-chunk live path (confirmed not
worth doing — see above). Fix the actual defect instead:

1. `TuiController` gets a tracked, sequential background queue
   (`_finalize_queue` / `_finalize_worker_task`) for finalize jobs. Both the
   manual "Speaker ID" trigger (`FinalizeSessionRequested`, ctrl+i on either
   tab) and auto-finalize-on-stop now go through `_enqueue_finalize(...)`
   instead of being awaited inline in `handle()` (which was itself awaited
   from Textual's key-binding dispatch — freezing the whole UI for the
   multi-minute WhisperX pass) or fired via an untracked `create_task`. The
   worker is started lazily on first enqueue (not in `__post_init__`, which
   runs before the asyncio event loop exists). Jobs run one at a time to
   avoid GPU/CPU contention.
2. `AppState.busy_operations: dict[str, str]` (label → status message) plus
   `BusyOperationStarted/Progress/Finished` actions drive a small
   `LoadingIndicator` + status line on the Live tab, so both finalize and
   summarize (already non-blocking via `run_worker`, just not visible) show
   that something is happening instead of the UI looking idle/frozen.
3. **Startup recovery**: on `AppStarted`, `find_unfinalized_sessions(...)`
   (ended session, non-empty transcript, every segment still `"unknown"`)
   scans sessions ended in the last 24h and re-enqueues them. Bounded to 24h
   and gated on `hf_token` being configured, so it only catches the
   steady-state "just quit right after stopping" case — not a surprise
   multi-hour GPU sweep of the whole history on every launch, and not an
   infinite retry loop for a session that legitimately has no HF token to
   diarize with.
4. **CLI backfill**: `live-transcriber finalize-pending [--dry-run]` runs the
   same `find_unfinalized_sessions` query with no time bound, so the user can
   deliberately re-diarize their existing backlog of orphaned sessions (24
   real ones found via `--dry-run` against a copy of their database) on their
   own schedule, with a progress bar. This is also the direct answer to "add
   CLI commands to check if diarization is working" — `speakers
   --session-id` already existed to inspect one session's result;
   `finalize-pending` finds and fixes the ones that never got one.

Explicitly out of scope (separate cleanup, not the reported symptom): the
dead `application/diarization_batch.py` chunk-reprocessing path, the
always-empty `diarization_segments` table, `DIARIZATION_NUM_SPEAKERS` being
silently ignored by the WhisperX finalize path, and raw `SPEAKER_00`-style
labels on mono recordings.

**Live tab editing**: add inline `Title` (`Input`), `Notes` (`TextArea`), and
`Attendees` (`Input`) fields directly to the Live tab's sidebar in `app.py`,
mirroring the Meetings tab's fields but without the autocomplete/speaker-alias
machinery (not requested, would meaningfully grow the change). Fields populate
from `Container.sessions.get(current_session_id)` whenever
`AppState.current_session_id` changes, and are disabled when there is no
current session. Saving is bound to `ctrl+s` (consistent with the Meetings
tab's own `ctrl+s` save binding, which is scoped to that tab's widget and does
not conflict — verified with a pilot test) and calls
`Container.sessions.update_details(...)` directly, then dispatches the
existing `SessionTitleUpdated` action so the header/status title and sessions
catalog stay in sync — reusing the persistence pattern already proven safe
during active recording, rather than inventing a new one.

### Rejected alternatives

- Live per-chunk pyannote diarization (see Context above) — technically
  unsound for this app's short, turn-taking chunks; would reproduce the
  complaint in a noisier form.
- Awaiting the finalize task before `self.exit()` on quit — trades the
  silent-drop bug for a hang-on-quit bug (WhisperX on a long meeting can take
  10–30 minutes). Survive-exit-without-blocking (queue + startup recovery)
  was chosen instead.
- A modal for title/notes/attendees editing (extending the existing
  title-only `EditSessionTitleScreen`/`m`+`e` flow) — reuses more existing
  code and avoids any focus/keybinding interaction with the always-visible
  Live tab. Rejected because the user asked specifically to improve the Live
  tab itself; a modal doesn't fix the discoverability problem and keeps the
  fields out of view while recording.

## Consequences

- No schema changes. No new required settings — `finalize-pending` and the
  queue/recovery mechanism work with what's already configured.
- `find_unfinalized_sessions` (in `application/finalize_service.py`) is the
  single shared query used by both the CLI backfill and startup recovery.
- Any future direct caller of `TuiController._run_finalize_for_session` must
  go through `_enqueue_finalize` instead — calling it directly re-introduces
  the UI-freeze bug.
- The Live tab's `_render_status` status line drops the redundant read-only
  `Title` row since the title is now shown (and editable) as its own input.
- Verified against real data (scratch copies of the user's database only —
  the actual database was never mutated by this work): finalize completes
  correctly on real audio, and `finalize-pending --dry-run` correctly listed
  24 real orphaned sessions. Running the real backfill (dropping `--dry-run`)
  is left to the user, since it's a long-running, resource-heavy operation
  over their own data.
