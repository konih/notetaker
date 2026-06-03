"""Interactive CLI review of detected slide candidates before saving."""

from __future__ import annotations

from collections.abc import Callable

from live_meeting_transcriber.domain.models import SlideCandidate


def format_timestamp(seconds: float) -> str:
    total = int(max(0.0, seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def review_slide_candidates(
    candidates: list[SlideCandidate],
    *,
    prompt_fn: Callable[[str], str] | None = None,
    echo_fn: Callable[[str], None] | None = None,
    accept_all: bool = False,
    reject_all: bool = False,
) -> list[SlideCandidate]:
    """Ask the user to confirm each candidate so we do not save spurious frames.

    Returns the subset the user accepted. When ``accept_all``/``reject_all`` is set,
    skips prompts (useful for tests and ``--yes-slides`` / ``--no-slides`` flags).
    """
    if not candidates:
        return []
    if reject_all:
        return []
    if accept_all:
        return list(candidates)

    read = prompt_fn or input
    write = echo_fn or print

    write("")
    write(f"Found {len(candidates)} slide candidate(s). Review each (y/n/a=all/q=quit):")
    write("")

    accepted: list[SlideCandidate] = []
    for i, cand in enumerate(candidates, start=1):
        ts = format_timestamp(cand.timestamp_seconds)
        preview = f"  preview: {cand.preview_path}" if cand.preview_path else ""
        write(f"[{i}/{len(candidates)}] {ts}  change={cand.change_score:.2f}{preview}")
        while True:
            ans = read("Keep this slide? [y/n/a/q]: ").strip().lower()
            if ans in ("y", "yes", ""):
                accepted.append(cand)
                break
            if ans in ("n", "no"):
                break
            if ans in ("a", "all"):
                accepted.extend(candidates[i - 1 :])
                write(f"Accepted remaining {len(candidates) - i + 1} slide(s).")
                return accepted
            if ans in ("q", "quit"):
                write(f"Stopped review; keeping {len(accepted)} slide(s) so far.")
                return accepted
            write("Please answer y, n, a (accept all remaining), or q (quit review).")

    write(f"Keeping {len(accepted)} of {len(candidates)} slide(s).")
    return accepted
