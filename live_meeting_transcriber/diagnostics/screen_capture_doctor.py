"""Doctor check for F6 live screen capture.

Availability (platform + ``screencapture`` binary) is probeable; the macOS Screen
Recording permission (TCC) is a human grant that cannot be verified headlessly —
the check therefore *reminds* about it instead of pretending to validate it.
"""

from __future__ import annotations

from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.diagnostics.diarization_doctor import CheckResult
from live_meeting_transcriber.domain.ports import ScreenCapture

_TCC_REMINDER = (
    "reminder: grant your terminal the Screen Recording permission "
    "(System Settings → Privacy & Security → Screen Recording) — this cannot be "
    "verified automatically; without it captures show only the desktop wallpaper"
)


def check_live_screen_capture(
    settings: Settings,
    *,
    screen: ScreenCapture | None = None,
) -> CheckResult:
    """Report whether the F6 live screen-capture loop can run on this machine."""
    name = "Live screen capture"
    if not settings.live_screen_capture_enabled:
        return CheckResult(
            name,
            True,
            "disabled (LIVE_SCREEN_CAPTURE_ENABLED=false — privacy default)",
        )
    if screen is None:
        from live_meeting_transcriber.screencap.cli import ScreencaptureCli

        screen = ScreencaptureCli()
    ok, reason = screen.availability()
    if not ok:
        return CheckResult(
            name,
            False,
            f"enabled but unavailable: {reason}",
            "Live capture needs macOS with the screencapture CLI; disable "
            "LIVE_SCREEN_CAPTURE_ENABLED on other platforms.",
        )
    return CheckResult(
        name,
        True,
        f"enabled, capturing every {settings.live_screen_capture_interval_seconds}s; "
        f"{_TCC_REMINDER}",
    )
