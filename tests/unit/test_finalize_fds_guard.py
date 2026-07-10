"""Regression tests for the P0 'bad value(s) in fds_to_keep' diarization crash.

While the Textual TUI runs it wraps the app in ``redirect_stdout``/``redirect_stderr``
whose stream returns ``fileno() == -1`` (textual/app.py:290). Offline finalize
(WhisperX + pyannote) runs in-process via ``asyncio.to_thread``; when WhisperX's model
load forks a child, the forking library reads ``sys.stdout.fileno()`` -> -1 and CPython's
``fork_exec`` raises ``ValueError: bad value(s) in fds_to_keep``. The CLI path is unaffected
because it keeps real std streams.

``finalize_session_offline`` must therefore run the pipeline with valid std file
descriptors. These tests are hermetic (no whisperx / no models).
"""

from __future__ import annotations

import asyncio
import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from live_meeting_transcriber.application import finalize_service
from live_meeting_transcriber.utils.std_streams import subprocess_safe_std_streams


class _FilenoMinusOne(io.TextIOBase):
    """Mimics Textual's console redirect stream: writable, isatty, but ``fileno() == -1``."""

    def write(self, s: str) -> int:  # discard, like a TUI capturing prints
        return len(s)

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return -1


def test_guard_provides_valid_fileno_and_restores() -> None:
    fake_in, fake_out, fake_err = _FilenoMinusOne(), _FilenoMinusOne(), _FilenoMinusOne()
    saved = (sys.stdin, sys.stdout, sys.stderr)
    sys.stdin, sys.stdout, sys.stderr = fake_in, fake_out, fake_err
    try:
        assert sys.stdout.fileno() == -1  # precondition: the poisoned TUI stream
        with subprocess_safe_std_streams():
            assert sys.stdin.fileno() >= 0
            assert sys.stdout.fileno() >= 0
            assert sys.stderr.fileno() >= 0
        # streams restored to exactly what they were
        assert sys.stdin is fake_in
        assert sys.stdout is fake_out
        assert sys.stderr is fake_err
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved


def test_finalize_offline_runs_pipeline_with_valid_std_fds(monkeypatch) -> None:
    """The offline (TUI) finalize path must give the WhisperX pipeline real std fds
    even when the surrounding process redirected std streams to ``fileno() == -1``."""
    fake_out, fake_err = _FilenoMinusOne(), _FilenoMinusOne()
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    seen: dict[str, int] = {}

    def fake_pipeline(**kwargs: object) -> list[object]:
        # This is what WhisperX's forking model-load effectively reads.
        seen["stdout"] = sys.stdout.fileno()
        seen["stderr"] = sys.stderr.fileno()
        return []

    monkeypatch.setattr(
        "live_meeting_transcriber.offline.whisperx_pipeline.run_whisperx_finalize",
        fake_pipeline,
    )
    monkeypatch.setattr(
        finalize_service,
        "_finalize_load_inputs",
        lambda **kw: (datetime(2026, 1, 1, tzinfo=timezone.utc), Path("full_session.wav"), []),
    )
    monkeypatch.setattr(
        finalize_service,
        "_finalize_persist_segments",
        lambda **kw: 0,
    )

    asyncio.run(
        finalize_service.finalize_session_offline(
            container=MagicMock(),
            settings=MagicMock(),
            session_id=uuid4(),
        )
    )

    assert seen["stdout"] >= 0, "pipeline saw an invalid stdout fileno (fds_to_keep crash)"
    assert seen["stderr"] >= 0, "pipeline saw an invalid stderr fileno (fds_to_keep crash)"
