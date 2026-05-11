from __future__ import annotations

import uuid
from datetime import datetime

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


def _touch(state: AppState, at: datetime) -> AppState:
    return state.model_copy(update={"last_updated_at": at})


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
                    "diarization_enabled": action.diarization_enabled,
                    "diarization_provider": action.diarization_provider,
                    "diarization_status": DiarizationStatus.disabled
                    if not action.diarization_enabled
                    else DiarizationStatus.pending,
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
        return _touch(
            state.model_copy(
                update={
                    "current_session_id": action.session_id,
                    "session_title": action.title,
                    "audio_source": action.audio_source,
                    "microphone_source": action.microphone_source,
                    "chunk_seconds": action.chunk_seconds,
                    "recording_status": RecordingStatus.recording,
                    "transcription_status": TranscriptionStatus.active,
                    "diarization_status": DiarizationStatus.active
                    if state.diarization_enabled
                    else DiarizationStatus.disabled,
                    "recent_transcript_segments": (),
                    "diarization_detected_speakers": frozenset(),
                }
            ),
            action.at,
        )

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
                    "diarization_status": DiarizationStatus.disabled
                    if not state.diarization_enabled
                    else DiarizationStatus.pending,
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
        return _touch(
            state.model_copy(
                update={
                    "recording_status": RecordingStatus.failed,
                    "transcription_status": TranscriptionStatus.failed,
                    "microphone_source": None,
                    "current_level_meter": None,
                    "diarization_status": DiarizationStatus.failed
                    if state.diarization_enabled
                    else DiarizationStatus.disabled,
                    "recent_errors": merged_errs,
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
            state.model_copy(update={"recent_transcript_segments": merged}),
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
        merged = state.diarization_detected_speakers | action.speakers
        return _touch(
            state.model_copy(update={"diarization_detected_speakers": merged}),
            action.at,
        )

    if isinstance(action, act.ErrorRaised):
        err = UiErrorState(
            id=str(uuid.uuid4()),
            message=action.message,
            at=action.at,
            acknowledged=False,
        )
        merged = (*state.recent_errors, err)[-_MAX_ERRORS:]
        return _touch(state.model_copy(update={"recent_errors": merged}), action.at)

    if isinstance(action, act.ErrorAcknowledged):
        merged = tuple(
            e.model_copy(update={"acknowledged": True}) if e.id == action.error_id else e
            for e in state.recent_errors
        )
        return _touch(state.model_copy(update={"recent_errors": merged}), action.at)

    if isinstance(action, act.WarningRaised):
        w = (*state.warnings, action.message)[-_MAX_WARNINGS:]
        return _touch(state.model_copy(update={"warnings": w}), action.at)

    if isinstance(action, act.NoticeRaised):
        n = (*state.notices, action.message)[-_MAX_NOTICES:]
        return _touch(state.model_copy(update={"notices": n}), action.at)

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
        updates: dict[str, object] = {"sessions_catalog": new_catalog}
        if state.current_session_id == action.session_id:
            updates["session_title"] = action.title
        return _touch(state.model_copy(update=updates), action.at)

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
            state.model_copy(update={"current_level_meter": action.level}),
            action.at,
        )

    return state
