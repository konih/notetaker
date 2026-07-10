from __future__ import annotations

import uuid
from datetime import datetime

from rich.markup import escape

from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    AppState,
    DiarizationStatus,
    RecordingStatus,
    SessionRowState,
    TranscriptionStatus,
    TranscriptLineState,
    UiErrorState,
)

_MAX_TRANSCRIPT_LINES = 200
_MAX_ERRORS = 40
_MAX_WARNINGS = 30
_MAX_NOTICES = 12
_MAX_UI_LOG_LINES = 500

# Warn once after this many consecutive empty chunks (no speech detected) — a strong
# hint that the input level is too low or the wrong audio device is selected.
_EMPTY_CHUNKS_WARN_THRESHOLD = 3
_LOW_AUDIO_WARNING = (
    "No speech detected in the audio yet. Check that the right input device is selected "
    "and the level is not too low. On macOS, capturing meeting/system audio needs a "
    "loopback device (e.g. BlackHole or an app audio device like 'Microsoft Teams Audio')."
)


def _touch(state: AppState, at: datetime) -> AppState:
    return state.model_copy(update={"last_updated_at": at})


def _format_ui_log_line(level: str, message: str, at: datetime) -> str:
    ts = at.isoformat(timespec="seconds").replace("T", " ")
    esc = escape(message)
    if level == "error":
        return f"[dim]{ts}[/] [red]{esc}[/]"
    if level == "warning":
        return f"[dim]{ts}[/] [yellow]{esc}[/]"
    return f"[dim]{ts}[/] {esc}"


def _append_ui_log(state: AppState, level: str, message: str, at: datetime) -> tuple[str, ...]:
    line = _format_ui_log_line(level, message, at)
    return (*state.ui_log_lines, line)[-_MAX_UI_LOG_LINES:]


def reduce(state: AppState, action: act.Action) -> AppState:
    """Pure reducer: no I/O, no side effects."""
    if isinstance(action, act.AppStarted):
        return _touch(state, action.at)

    if isinstance(action, act.SettingsLoaded):
        return _touch(
            state.model_copy(
                update={
                    "transcription_provider": action.transcription_provider,
                    "transcription_model": action.transcription_model,
                    "summarization_provider": action.summarization_provider,
                    "summary_model": action.summary_model,
                    "database_url": action.database_url,
                    "chunk_seconds": action.audio_chunk_seconds,
                    "audio_sample_rate": action.audio_sample_rate,
                    "audio_channels": action.audio_channels,
                    "audio_stereo_mode": action.audio_stereo_mode,
                    "diarization_enabled": action.diarization_enabled,
                    "diarization_provider": action.diarization_provider,
                    "finalize_on_session_stop": action.finalize_on_session_stop,
                    "whisperx_model": action.whisperx_model,
                    "whisperx_skip_alignment": action.whisperx_skip_alignment,
                    "hf_token_configured": action.hf_token_configured,
                    "diarization_status": DiarizationStatus.disabled,
                    "log_file_path": action.log_file_resolved,
                    "audio_include_microphone": action.audio_include_microphone,
                }
            ),
            action.at,
        )

    if isinstance(action, act.RecordingStartRequested):
        return _touch(
            state.model_copy(
                update={
                    "recording_status": RecordingStatus.starting,
                    "session_title": action.title,
                    "audio_source": action.audio_source or state.audio_source,
                }
            ),
            action.at,
        )

    if isinstance(action, act.RecordingStarted):
        updates: dict[str, object] = {
            "current_session_id": action.session_id,
            "session_title": action.title,
            "audio_source": action.audio_source,
            "microphone_source": action.microphone_source,
            "chunk_seconds": action.chunk_seconds,
            "recording_status": RecordingStatus.recording,
            "transcription_status": TranscriptionStatus.active,
            # Elapsed timer starts now; on resume it measures this segment, not the original.
            "recording_started_at": action.at,
            "consecutive_empty_chunks": 0,
            "low_audio_warning_shown": False,
            "diarization_status": DiarizationStatus.active
            if (
                state.audio_channels >= 2 and state.audio_stereo_mode.strip().lower() == "dual_path"
            )
            else DiarizationStatus.disabled,
        }
        if action.resumed:
            updates["recent_transcript_segments"] = action.loaded_transcript_segments
            updates["diarization_detected_speakers"] = frozenset(
                s.speaker
                for s in action.loaded_transcript_segments
                if s.speaker and s.speaker not in ("unknown", "")
            )
        else:
            updates["recent_transcript_segments"] = ()
            updates["diarization_detected_speakers"] = frozenset()
        return _touch(state.model_copy(update=updates), action.at)

    if isinstance(action, act.RecordingStopRequested):
        if state.recording_status not in (
            RecordingStatus.recording,
            RecordingStatus.starting,
        ):
            return _touch(state, action.at)
        return _touch(
            state.model_copy(update={"recording_status": RecordingStatus.stopping}),
            action.at,
        )

    if isinstance(action, act.RecordingStopped):
        return _touch(
            state.model_copy(
                update={
                    "recording_status": RecordingStatus.stopped,
                    "transcription_status": TranscriptionStatus.idle,
                    "microphone_source": None,
                    "diarization_status": DiarizationStatus.disabled,
                    "recording_started_at": None,
                }
            ),
            action.at,
        )

    if isinstance(action, act.RecordingFailed):
        err = UiErrorState(
            id=str(uuid.uuid4()),
            message=action.message,
            at=action.at,
            acknowledged=False,
        )
        merged_errs = (*state.recent_errors, err)[-_MAX_ERRORS:]
        logs = _append_ui_log(state, "error", action.message, action.at)
        return _touch(
            state.model_copy(
                update={
                    "recording_status": RecordingStatus.failed,
                    "transcription_status": TranscriptionStatus.failed,
                    "microphone_source": None,
                    "current_level_meter": None,
                    "diarization_status": DiarizationStatus.failed
                    if state.diarization_status == DiarizationStatus.active
                    else DiarizationStatus.disabled,
                    "recording_started_at": None,
                    "recent_errors": merged_errs,
                    "ui_log_lines": logs,
                }
            ),
            action.at,
        )

    if isinstance(action, act.AudioSourceChanged):
        return _touch(state.model_copy(update={"audio_source": action.source}), action.at)

    if isinstance(action, act.TranscriptSegmentReceived):
        line = TranscriptLineState(
            id=action.segment_id,
            session_id=action.session_id,
            started_at=action.started_at,
            ended_at=action.ended_at,
            text=action.text,
            speaker=action.speaker,
        )
        merged = (*state.recent_transcript_segments, line)[-_MAX_TRANSCRIPT_LINES:]
        return _touch(
            state.model_copy(
                update={
                    "recent_transcript_segments": merged,
                    "consecutive_empty_chunks": 0,
                }
            ),
            action.at,
        )

    if isinstance(action, act.DiarizationSegmentReceived):
        updated: list[TranscriptLineState] = []
        for seg in state.recent_transcript_segments:
            if seg.id == action.segment_id:
                updated.append(seg.model_copy(update={"speaker": action.speaker}))
            else:
                updated.append(seg)
        return _touch(
            state.model_copy(update={"recent_transcript_segments": tuple(updated)}),
            action.at,
        )

    if isinstance(action, act.SpeakerAliasUpdated):
        aliases = dict(state.speaker_aliases)
        aliases[action.speaker_key] = action.alias
        return _touch(state.model_copy(update={"speaker_aliases": aliases}), action.at)

    if isinstance(action, act.SpeakerAliasesLoaded):
        return _touch(
            state.model_copy(update={"speaker_aliases": dict(action.aliases)}),
            action.at,
        )

    if isinstance(action, act.DiarizationSpeakersDetected):
        merged_speakers = state.diarization_detected_speakers | action.speakers
        return _touch(
            state.model_copy(update={"diarization_detected_speakers": merged_speakers}),
            action.at,
        )

    if isinstance(action, act.ErrorRaised):
        err = UiErrorState(
            id=str(uuid.uuid4()),
            message=action.message,
            at=action.at,
            acknowledged=False,
        )
        merged_errors = (*state.recent_errors, err)[-_MAX_ERRORS:]
        logs = _append_ui_log(state, "error", action.message, action.at)
        return _touch(
            state.model_copy(update={"recent_errors": merged_errors, "ui_log_lines": logs}),
            action.at,
        )

    if isinstance(action, act.ErrorAcknowledged):
        acked_errors = tuple(
            e.model_copy(update={"acknowledged": True}) if e.id == action.error_id else e
            for e in state.recent_errors
        )
        return _touch(state.model_copy(update={"recent_errors": acked_errors}), action.at)

    if isinstance(action, act.WarningRaised):
        w = (*state.warnings, action.message)[-_MAX_WARNINGS:]
        logs = _append_ui_log(state, "warning", action.message, action.at)
        return _touch(state.model_copy(update={"warnings": w, "ui_log_lines": logs}), action.at)

    if isinstance(action, act.UiLogLineAdded):
        lvl = action.level if action.level in ("info", "warning", "error") else "info"
        logs = _append_ui_log(state, lvl, action.message, action.at)
        return _touch(state.model_copy(update={"ui_log_lines": logs}), action.at)

    if isinstance(action, act.NoticeRaised):
        n = (*state.notices, action.message)[-_MAX_NOTICES:]
        return _touch(state.model_copy(update={"notices": n}), action.at)

    if isinstance(action, act.FinalizeSessionSucceeded):
        msg = (
            f"Speaker ID / finalize complete ({action.segment_count} segment(s)) "
            f"for session {action.session_id}."
        )
        n = (*state.notices, msg)[-_MAX_NOTICES:]
        finalize_updates: dict[str, object] = {
            "pending_meeting_detail_reload": action.session_id,
            "notices": n,
        }
        if action.live_lines is not None:
            finalize_updates["recent_transcript_segments"] = action.live_lines
        return _touch(state.model_copy(update=finalize_updates), action.at)

    if isinstance(action, act.DetailReloadAcknowledged):
        return _touch(
            state.model_copy(update={"pending_meeting_detail_reload": None}),
            action.at,
        )

    if isinstance(action, act.SettingsScreenOpened):
        return _touch(state.model_copy(update={"settings_screen_open": True}), action.at)

    if isinstance(action, act.SettingsScreenClosed):
        return _touch(state.model_copy(update={"settings_screen_open": False}), action.at)

    if isinstance(action, act.SessionsRefreshRequested):
        return _touch(state.model_copy(update={"sessions_loading": True}), action.at)

    if isinstance(action, act.SessionsListLoaded):
        return _touch(
            state.model_copy(update={"sessions_catalog": action.rows, "sessions_loading": False}),
            action.at,
        )

    if isinstance(action, act.SessionsScreenOpened):
        return _touch(state.model_copy(update={"sessions_screen_open": True}), action.at)

    if isinstance(action, act.SessionsScreenClosed):
        return _touch(state.model_copy(update={"sessions_screen_open": False}), action.at)

    if isinstance(action, act.SessionTitleUpdated):
        sid = str(action.session_id)
        new_catalog: tuple[SessionRowState, ...] = tuple(
            r.model_copy(update={"title": action.title}) if r.id == sid else r
            for r in state.sessions_catalog
        )
        title_updates: dict[str, object] = {"sessions_catalog": new_catalog}
        if state.current_session_id == action.session_id:
            title_updates["session_title"] = action.title
        return _touch(state.model_copy(update=title_updates), action.at)

    if isinstance(action, act.TranscriptionStatusChanged):
        return _touch(
            state.model_copy(update={"transcription_status": action.status}),
            action.at,
        )

    if isinstance(action, act.DiarizationStatusChanged):
        return _touch(
            state.model_copy(update={"diarization_status": action.status}),
            action.at,
        )

    if isinstance(action, act.AudioLevelUpdated):
        return _touch(
            state.model_copy(
                update={"current_level_meter": action.level, "last_level_at": action.at}
            ),
            action.at,
        )

    if isinstance(action, act.AudioSourcesSelected):
        return _touch(
            state.model_copy(
                update={
                    "audio_source": action.monitor_source,
                    "configured_microphone_source": action.microphone_source,
                }
            ),
            action.at,
        )

    if isinstance(action, act.TranscriptionChunkEmptyObserved):
        count = state.consecutive_empty_chunks + 1
        empty_updates: dict[str, object] = {"consecutive_empty_chunks": count}
        if count >= _EMPTY_CHUNKS_WARN_THRESHOLD and not state.low_audio_warning_shown:
            empty_updates["low_audio_warning_shown"] = True
            empty_updates["warnings"] = (*state.warnings, _LOW_AUDIO_WARNING)[-_MAX_WARNINGS:]
            empty_updates["ui_log_lines"] = _append_ui_log(
                state, "warning", _LOW_AUDIO_WARNING, action.at
            )
        return _touch(state.model_copy(update=empty_updates), action.at)

    return state
