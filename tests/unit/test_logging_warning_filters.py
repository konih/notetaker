"""B1 — the noisy pyannote/torchcodec UserWarning is suppressed (misleading, inert)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import warnings

# The real pyannote.audio warning begins with a leading newline before "torchcodec";
# reproduce that exactly so the test guards the anchored-regex match, not a cleaned-up
# variant.
_TORCHCODEC_MSG = "\ntorchcodec is not installed correctly so built-in audio decoding will fail"


def test_torchcodec_warning_filter_suppresses_only_the_noisy_warning() -> None:
    """The installed filter drops the torchcodec warning but keeps unrelated ones."""
    from live_meeting_transcriber.observability.logging import (
        _silence_noisy_dependency_warnings,
    )

    with warnings.catch_warnings(record=True) as caught:
        # ``record=True`` resets filters to a single "always"; re-installing prepends
        # our "ignore" filter so it wins the first-match lookup.
        _silence_noisy_dependency_warnings()
        warnings.warn(_TORCHCODEC_MSG, UserWarning, stacklevel=1)
        warnings.warn("some unrelated pyannote warning", UserWarning, stacklevel=1)

    messages = [str(w.message) for w in caught]
    assert not any("torchcodec" in m for m in messages), messages
    assert any("unrelated" in m for m in messages), messages


def test_importing_logging_module_suppresses_warning_in_fresh_process() -> None:
    """Real acceptance: merely importing the logging module installs the filter early.

    Runs in a fresh interpreter so the filter must be registered at *import* scope
    (not just inside ``configure_logging``) to win the race against pyannote's lazy
    import — the exact failure mode an in-process test would hide.
    """
    code = textwrap.dedent(
        f"""
        import sys, warnings
        # Import alone must install the filter (no configure_logging call).
        import live_meeting_transcriber.observability.logging  # noqa: F401
        warnings.warn({_TORCHCODEC_MSG!r}, UserWarning, stacklevel=1)
        warnings.warn("keep this unrelated warning", UserWarning, stacklevel=1)
        sys.stderr.write("SMOKE_DONE\\n")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "SMOKE_DONE" in result.stderr
    assert "torchcodec" not in result.stderr, result.stderr
    assert "keep this unrelated warning" in result.stderr, result.stderr
