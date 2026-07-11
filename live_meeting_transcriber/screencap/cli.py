"""macOS ``screencapture``-backed implementation of the ``ScreenCapture`` port (F6).

Shells out to the system ``screencapture`` CLI (`-x`: no shutter sound — this runs
mid-meeting). Binary discovery, the subprocess runner, and the platform are injected
so unit tests stay hermetic and Linux CI never needs the binary.

macOS TCC caveat: the Screen Recording permission cannot be probed headlessly.
Without the grant, modern macOS lets ``screencapture`` exit 0 but the image shows
only the desktop wallpaper — surfacing that is doctor/documentation territory, not
something this adapter can detect.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path


def _run_quiet(cmd: Sequence[str]) -> int:
    """Run the capture command with all output swallowed; return its exit code."""
    proc = subprocess.run(list(cmd), capture_output=True, check=False)
    return proc.returncode


@dataclass(frozen=True)
class ScreencaptureCli:
    """``ScreenCapture`` port adapter for the macOS ``screencapture`` CLI."""

    binary: str = "screencapture"
    which: Callable[[str], str | None] = shutil.which
    runner: Callable[[Sequence[str]], int] = _run_quiet
    platform: str = field(default_factory=lambda: sys.platform)

    def availability(self) -> tuple[bool, str | None]:
        if self.platform != "darwin":
            return (False, "live screen capture requires macOS (the screencapture CLI)")
        if self.which(self.binary) is None:
            return (False, "screencapture binary not found on PATH")
        return (True, None)

    def capture(self, output_path: Path) -> bool:
        ok, _reason = self.availability()
        if not ok:
            return False
        resolved = self.which(self.binary)
        if resolved is None:  # pragma: no cover - availability() already gates this
            return False
        # -x: no sound; -t png: explicit format regardless of user defaults.
        rc = self.runner([resolved, "-x", "-t", "png", str(output_path)])
        if rc != 0:
            return False
        return output_path.is_file() and output_path.stat().st_size > 0
