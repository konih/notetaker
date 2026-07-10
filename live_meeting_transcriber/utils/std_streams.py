"""Process std-stream helpers for subprocess-safe offline work.

The Textual TUI wraps the running app in ``redirect_stdout``/``redirect_stderr`` whose
stream returns ``fileno() == -1`` (see ``textual/app.py``). Offline finalize (WhisperX +
pyannote) runs in-process via ``asyncio.to_thread``; when a WhisperX/pyannote step forks a
child process the forking library reads ``sys.stdout.fileno()`` -> -1, which CPython's
``fork_exec`` rejects with ``ValueError: bad value(s) in fds_to_keep``. The CLI path never
hits this because it keeps the real terminal streams.

:func:`subprocess_safe_std_streams` temporarily points ``sys.stdin``/``stdout``/``stderr``
at ``os.devnull`` (real, valid file descriptors) so any child-spawning library gets a usable
fileno. ``os.devnull`` — not the real terminal — also means WhisperX/tqdm progress output is
discarded rather than dumped over the TUI. File logging is unaffected: it uses a dedicated
``RotatingFileHandler`` and structlog captures its stdout reference at configure time.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator


@contextlib.contextmanager
def subprocess_safe_std_streams() -> Iterator[None]:
    """Point ``sys.stdin``/``stdout``/``stderr`` at ``os.devnull`` for the duration.

    Guarantees each stream exposes a valid ``fileno()`` so child-process spawning inside
    (e.g. WhisperX model load) does not raise ``bad value(s) in fds_to_keep`` under a TUI
    that redirected the std streams. The original stream objects are always restored.
    """
    saved = (sys.stdin, sys.stdout, sys.stderr)
    devnull_in = open(os.devnull)  # noqa: SIM115 — closed in finally
    devnull_out = open(os.devnull, "w")  # noqa: SIM115
    devnull_err = open(os.devnull, "w")  # noqa: SIM115
    sys.stdin, sys.stdout, sys.stderr = devnull_in, devnull_out, devnull_err
    try:
        yield
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved
        for stream in (devnull_in, devnull_out, devnull_err):
            with contextlib.suppress(Exception):
                stream.close()
