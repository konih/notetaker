"""Unit tests for TUI slide preview helpers and screen."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from live_meeting_transcriber.application.slide_preview_service import SlidePreviewResult
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.models import SlideCandidate, SlideDetectionParams
from live_meeting_transcriber.ui.tui.slide_preview_helpers import (
    accepted_candidates,
    build_slide_params,
    format_candidate_count_hint,
    format_candidate_label,
    inline_image_unsupported_message,
    normalize_strategy,
    open_image_externally,
    slide_param_focus_hint,
    terminal_supports_inline_images,
    try_chafa_ascii_preview,
)
from live_meeting_transcriber.ui.tui.slide_preview_screen import SlidePreviewScreen
from textual.app import App
from textual.widgets import Button


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_build_slide_params_uses_settings_defaults_for_empty_fields() -> None:
    s = _settings(
        video_slide_sample_interval_seconds=3.0,
        video_slide_change_threshold=0.2,
        video_slide_min_interval_seconds=10.0,
        video_slide_max_candidates=50,
    )
    params = build_slide_params(
        sample_interval="",
        threshold="",
        min_interval="",
        max_candidates="",
        settings=s,
    )
    assert params.sample_interval_seconds == 3.0
    assert params.change_threshold == 0.2
    assert params.min_slide_interval_seconds == 10.0
    assert params.max_candidates == 50


def test_build_slide_params_parses_overrides() -> None:
    s = _settings()
    params = build_slide_params(
        sample_interval="1.5",
        threshold="0.25",
        min_interval="20",
        max_candidates="80",
        settings=s,
    )
    assert params == SlideDetectionParams(
        sample_interval_seconds=1.5,
        change_threshold=0.25,
        min_slide_interval_seconds=20.0,
        max_candidates=80,
    )


def test_normalize_strategy_falls_back_to_settings() -> None:
    s = _settings(video_slide_strategy="ffmpeg_scene")
    assert normalize_strategy("", settings=s) == "ffmpeg_scene"
    assert normalize_strategy("frame_diff", settings=s) == "frame_diff"


def test_format_candidate_label_marks_review_state() -> None:
    cand = SlideCandidate(timestamp_seconds=65.0, change_score=0.33, preview_path=None)
    assert "1:05" in format_candidate_label(0, cand, keep=None)
    assert "✓" in format_candidate_label(0, cand, keep=True)
    assert "✗" in format_candidate_label(0, cand, keep=False)


def test_accepted_candidates_filters_kept_rows() -> None:
    cands = [
        SlideCandidate(timestamp_seconds=1.0, change_score=0.1),
        SlideCandidate(timestamp_seconds=2.0, change_score=0.2),
        SlideCandidate(timestamp_seconds=3.0, change_score=0.3),
    ]
    review: dict[int, bool | None] = {0: True, 1: False, 2: True}
    accepted = accepted_candidates(cands, review)
    assert accepted == [cands[0], cands[2]]


def test_open_image_externally_no_file(tmp_path: Path) -> None:
    assert open_image_externally(tmp_path / "missing.png") is False


def test_open_image_externally_launches_viewer(tmp_path: Path) -> None:
    png = tmp_path / "slide.png"
    png.write_bytes(b"png")
    with (
        patch(
            "live_meeting_transcriber.ui.tui.slide_preview_helpers.shutil.which",
            return_value="/usr/bin/xdg-open",
        ),
        patch("live_meeting_transcriber.ui.tui.slide_preview_helpers.subprocess.Popen") as popen,
    ):
        assert open_image_externally(png) is True
        popen.assert_called_once()
        assert popen.call_args.args[0] == ["/usr/bin/xdg-open", str(png.resolve())]


def test_inline_image_unsupported_message_mentions_o() -> None:
    msg = inline_image_unsupported_message()
    assert "[bold]o[/]" in msg
    assert "Kitty" in msg


def test_slide_param_focus_hint_known_ids() -> None:
    assert "sensitive" in slide_param_focus_hint("slide-threshold").lower()
    assert slide_param_focus_hint("unknown") == "Select a field above for a short hint."


def test_terminal_supports_inline_images_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    import live_meeting_transcriber.ui.tui.slide_preview_helpers as helpers

    monkeypatch.setattr(helpers, "_INLINE_IMAGES_SUPPORTED", None)
    monkeypatch.setattr(helpers, "_INLINE_IMAGE_MODE", None)
    monkeypatch.setattr(helpers, "_probe_inline_image_mode", lambda: "graphics")
    assert terminal_supports_inline_images() is True


def test_try_chafa_ascii_preview_without_chafa(tmp_path: Path) -> None:
    png = tmp_path / "slide.png"
    png.write_bytes(b"png")
    with patch(
        "live_meeting_transcriber.ui.tui.slide_preview_helpers.shutil.which",
        return_value=None,
    ):
        assert try_chafa_ascii_preview(png) is None


def test_format_candidate_count_hint_flags_many() -> None:
    hint = format_candidate_count_hint(count=20, duration_seconds=120.0, min_interval_seconds=15.0)
    assert "20 candidate(s) in 120s" in hint
    assert "many" in hint


def test_format_candidate_count_hint_flags_few() -> None:
    hint = format_candidate_count_hint(count=1, duration_seconds=120.0, min_interval_seconds=15.0)
    assert "few" in hint


def test_build_slide_params_invalid_raises() -> None:
    s = _settings()
    with pytest.raises(ValueError):
        build_slide_params(
            sample_interval="not-a-number",
            threshold="0.1",
            min_interval="1",
            max_candidates="10",
            settings=s,
        )


@pytest.mark.asyncio
async def test_slide_preview_screen_populates_table_after_async_preview(tmp_path: Path) -> None:
    sid = uuid4()
    settings = _settings(database_url=f"sqlite:///{tmp_path / 'app.db'}")
    container = MagicMock()
    container.settings = settings
    candidates = [
        SlideCandidate(
            timestamp_seconds=float(i * 10 + 5),
            change_score=0.4 + i * 0.05,
            preview_path=tmp_path / f"candidate_{i:03d}.png",
        )
        for i in range(5)
    ]
    preview_result = SlidePreviewResult(
        session_id=sid,
        strategy="frame_diff",
        duration_seconds=120.0,
        video_path=tmp_path / "video.mp4",
        candidates=candidates,
        preview_dir=tmp_path / "previews",
    )

    class PreviewTestApp(App[None]):
        CSS = """
        #slide-preview-dialog { height: 40; layout: vertical; overflow: hidden; }
        #slide-preview-split { height: 1fr; min-height: 8; }
        #slide-candidates-table { height: 1fr; min-height: 4; }
        #slide-preview-actions { dock: bottom; height: auto; }
        #slide-preview-hint { dock: bottom; height: auto; }
        """

        def __init__(self) -> None:
            super().__init__()
            self._screen = SlidePreviewScreen(container=container, session_id=sid)

        async def on_mount(self) -> None:
            await self.push_screen(self._screen)

    with (
        patch(
            "live_meeting_transcriber.ui.tui.slide_preview_screen.terminal_supports_inline_images",
            return_value=False,
        ),
        patch(
            "live_meeting_transcriber.ui.tui.slide_preview_screen.SlidePreviewService",
        ) as mock_svc_cls,
    ):
        mock_svc_cls.return_value.preview = AsyncMock(return_value=preview_result)
        async with PreviewTestApp().run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, SlidePreviewScreen)
            table = screen._get_candidates_table()
            assert table is not None
            assert table.row_count == 5
            assert table.cursor_row == 0
            assert table.has_focus
            split = screen.query_one("#slide-preview-split")
            assert split.size.height >= 4
            apply_btn = screen.query_one("#slide-apply-btn", Button)
            apply_all_btn = screen.query_one("#slide-apply-all-btn", Button)
            assert apply_all_btn.disabled is False
            assert apply_btn.disabled is True
            assert screen._result is not None
            assert len(screen._result.candidates) == 5
            mock_svc_cls.return_value.preview.assert_awaited_once()
