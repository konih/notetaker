"""Live screen-capture loop for recording sessions (F6).

Privacy: gated behind ``LIVE_SCREEN_CAPTURE_ENABLED`` (default OFF) — the loop
no-ops unless the operator explicitly opted in. When enabled it periodically
captures the screen (via the ``ScreenCapture`` port) into
``sessions/<id>/screenshots/`` and journals each shot in ``captures.json`` so
markdown exports can interleave the images with the transcript — visual context
for "who was speaking" during later speaker naming.

Degrades gracefully: an unavailable platform or a failing capture (e.g. the macOS
Screen Recording permission was never granted) emits one ``ScreenCaptureUnavailable``
warning event and stops the loop; it never disturbs the recording itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.domain.application_events import (
    ApplicationEvent,
    ScreenCaptureShotTaken,
    ScreenCaptureUnavailable,
)
from live_meeting_transcriber.domain.ports import ScreenCapture
from live_meeting_transcriber.domain.session_audio import (
    live_captures_dir,
    live_captures_manifest_path,
    session_audio_dir,
)
from live_meeting_transcriber.observability.logging import get_logger
from live_meeting_transcriber.utils.time import utc_now

_TCC_HINT = (
    "If captures fail or show only the wallpaper on macOS, grant your terminal the "
    "Screen Recording permission (System Settings → Privacy & Security → Screen Recording)."
)


def _emit(
    sink: Callable[[ApplicationEvent], None] | None,
    event: ApplicationEvent,
) -> None:
    if sink is not None:
        sink(event)


def _load_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


@dataclass(frozen=True)
class LiveScreenCaptureLoop:
    """Periodic screen capture alongside ``Recorder.record_forever`` (F6)."""

    screen: ScreenCapture
    data_dir: Path
    enabled: bool
    interval_seconds: int
    # Injected for deterministic tests; production uses asyncio.sleep.
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep

    async def run(
        self,
        *,
        session_id: UUID,
        on_application_event: Callable[[ApplicationEvent], None] | None = None,
    ) -> None:
        if not self.enabled:
            return
        log = get_logger(component="live_capture", session_id=str(session_id))

        ok, reason = self.screen.availability()
        if not ok:
            message = f"Live screen capture is enabled but unavailable: {reason}"
            log.warning("screen_capture_unavailable", reason=reason)
            _emit(
                on_application_event,
                ScreenCaptureUnavailable(session_id=session_id, message=message, at=utc_now()),
            )
            return

        captures_dir = live_captures_dir(session_audio_dir(self.data_dir, session_id))
        captures_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = live_captures_manifest_path(captures_dir.parent)
        manifest = _load_manifest(manifest_path)
        index = len(manifest)
        shot_count = 0

        while True:
            at = utc_now()
            name = f"capture_{at.strftime('%Y%m%dT%H%M%SZ')}_{index:03d}.png"
            path = captures_dir / name
            captured = await asyncio.to_thread(self.screen.capture, path)
            if not captured:
                message = (
                    f"Live screen capture failed (screencapture wrote no image to {path.name}); "
                    f"stopping captures for this session. {_TCC_HINT}"
                )
                log.warning("screen_capture_failed", path=str(path))
                _emit(
                    on_application_event,
                    ScreenCaptureUnavailable(session_id=session_id, message=message, at=utc_now()),
                )
                return
            manifest.append({"path": name, "captured_at": at.isoformat()})
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            index += 1
            shot_count += 1
            log.info("screen_capture_shot", path=str(path), shot_count=shot_count)
            _emit(
                on_application_event,
                ScreenCaptureShotTaken(
                    session_id=session_id, path=path, shot_count=shot_count, at=at
                ),
            )
            await self.sleeper(float(self.interval_seconds))
