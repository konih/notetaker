from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.obsidian.meeting_export import write_dual_export
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.audio.sources import resolve_microphone_source
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.application_events import ApplicationEvent
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import RecordingStatus, SessionRowState
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.utils.time import utc_now


def _settings_loaded(settings: Settings, at: datetime) -> act.SettingsLoaded:
    return act.SettingsLoaded(
        transcription_provider=settings.transcription_provider,
        transcription_model=settings.transcription_model,
        summarization_provider=settings.llm_provider,
        summary_model=settings.summary_model,
        database_url=settings.database_url,
        audio_chunk_seconds=settings.audio_chunk_seconds,
        audio_sample_rate=settings.audio_sample_rate,
        audio_channels=settings.audio_channels,
        diarization_enabled=settings.diarization_enabled,
        diarization_provider=settings.diarization_provider,
        log_file_resolved=str(settings.resolved_log_file()),
        audio_include_microphone=settings.audio_include_microphone,
        at=at,
    )


@dataclass
class TuiController:
    """Async side effects for the TUI (recording, settings bootstrap, sessions)."""

    store: Store
    container: Container
    settings: Settings
    _session_service: SessionService = field(init=False)
    _record_task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._session_service = SessionService(
            sessions=self.container.sessions,
            transcripts=self.container.transcripts,
            summaries=self.container.summaries,
            summarizer=self.container.summarizer,
            session_speakers=self.container.session_speakers,
        )

    async def _load_sessions_catalog(self, store: Store) -> None:
        try:
            sessions = self.container.sessions.list()
        except Exception as e:
            store.dispatch(
                act.ErrorRaised(message=f"Failed to list sessions: {e}", at=utc_now())
            )
            store.dispatch(act.SessionsListLoaded(rows=tuple(), at=utc_now()))
            return
        rows = tuple(
            SessionRowState(
                id=str(s.id),
                title=s.title,
                started_at=s.started_at,
                ended_at=s.ended_at,
            )
            for s in sessions
        )
        store.dispatch(act.SessionsListLoaded(rows=rows, at=utc_now()))

    async def handle(self, store: Store, action: act.Action) -> None:
        if isinstance(action, act.AppStarted):
            store.dispatch(_settings_loaded(self.settings, action.at))
            store.dispatch(act.SessionsRefreshRequested(at=utc_now()))
            await self._load_sessions_catalog(store)

        elif isinstance(action, act.SessionsRefreshRequested):
            await self._load_sessions_catalog(store)

        elif isinstance(action, act.SessionTitleCommitRequested):
            title = action.new_title.strip()
            if not title:
                store.dispatch(act.ErrorRaised(message="Title must not be empty.", at=utc_now()))
                return
            updated = self.container.sessions.update_title(action.session_id, title)
            if updated is None:
                store.dispatch(act.ErrorRaised(message="Session not found.", at=utc_now()))
                return
            store.dispatch(
                act.SessionTitleUpdated(
                    session_id=action.session_id,
                    title=updated.title,
                    at=utc_now(),
                )
            )

        elif isinstance(action, act.RecordingStartRequested):
            if self._record_task is not None and not self._record_task.done():
                store.dispatch(
                    act.WarningRaised(message="Recording already in progress.", at=utc_now())
                )
                return

            if action.resume_session_id is not None:
                existing = self.container.sessions.get(action.resume_session_id)
                if existing is None:
                    store.dispatch(
                        act.RecordingFailed(message="Session not found; cannot continue recording.", at=utc_now())
                    )
                    return
                session = self.container.sessions.reopen(action.resume_session_id)
                if session is None:
                    store.dispatch(
                        act.RecordingFailed(message="Could not reopen session for recording.", at=utc_now())
                    )
                    return
            else:
                try:
                    session = self._session_service.create_session(title=action.title)
                except Exception as e:
                    store.dispatch(act.RecordingFailed(message=str(e), at=utc_now()))
                    return

            source = action.audio_source or self.container.devices.get_default_monitor_source()
            if not source:
                store.dispatch(
                    act.RecordingFailed(
                        message="No monitor source; set --source or configure default sink.",
                        at=utc_now(),
                    )
                )
                return

            mic = resolve_microphone_source(self.settings, self.container.devices)
            if self.settings.audio_include_microphone and mic is None:
                store.dispatch(
                    act.WarningRaised(
                        message="Microphone mix requested but no default mic found; "
                        "set AUDIO_MICROPHONE_SOURCE or use monitor-only (AUDIO_INCLUDE_MICROPHONE=false).",
                        at=utc_now(),
                    )
                )

            chunk_seconds = self.settings.audio_chunk_seconds
            store.dispatch(
                act.RecordingStarted(
                    session_id=session.id,
                    title=session.title,
                    audio_source=source,
                    microphone_source=mic,
                    chunk_seconds=chunk_seconds,
                    at=utc_now(),
                )
            )
            aliases = self.container.session_speakers.get_map(session.id)
            store.dispatch(act.SpeakerAliasesLoaded(aliases=dict(aliases), at=utc_now()))

            chunk_dir = (self.settings.ensure_data_dir() / "chunks" / str(session.id)).resolve()
            recorder = Recorder(
                audio=self.container.audio,
                transcriber=self.container.transcriber,
                diarizer=self.container.diarizer,
                transcripts=self.container.transcripts,
                diarization_segments=self.container.diarization_segments,
                keep_audio_chunks=self.settings.keep_audio_chunks,
                chunk_output_dir=chunk_dir,
                diarization_enabled=self.settings.diarization_enabled,
            )

            def emit(ev: ApplicationEvent) -> None:
                for ui_action in application_events_to_actions(ev):
                    self.store.dispatch(ui_action)

            async def run() -> None:
                await recorder.record_forever(
                    session_id=session.id,
                    source=source,
                    microphone_source=mic,
                    chunk_seconds=chunk_seconds,
                    sample_rate_hz=self.settings.audio_sample_rate,
                    channels=self.settings.audio_channels,
                    on_application_event=emit,
                )

            self._record_task = asyncio.create_task(run())

        elif isinstance(action, act.ExportMarkdownRequested):
            st = store.get_state()
            sid = action.session_id if action.session_id is not None else st.current_session_id
            if sid is None:
                store.dispatch(
                    act.ErrorRaised(
                        message="No session to export. On Live tab press r to record; on Meetings tab select a row and press w.",
                        at=utc_now(),
                    )
                )
                return
            session = self.container.sessions.get(sid)
            if session is None:
                store.dispatch(act.ErrorRaised(message="Session not found in database.", at=utc_now()))
                return
            segments = self.container.transcripts.list_by_session(sid)
            summary = self.container.summaries.get_by_session(sid)
            spk = self.container.session_speakers.get_map(sid)
            try:
                app_path, obs_path = write_dual_export(
                    app_base_dir=self.settings.ensure_data_dir(),
                    session=session,
                    segments=segments,
                    summary=summary,
                    speaker_display=spk if spk else None,
                    obsidian_meetings_dir=self.settings.obsidian_meetings_dir,
                    obsidian_meeting_template=self.settings.obsidian_meeting_template,
                    screenshots_source_dir=self.settings.effective_screenshots_source_dir(),
                    obsidian_screenshots_dir=self.settings.obsidian_screenshots_dir,
                )
            except Exception as e:
                store.dispatch(act.ErrorRaised(message=f"Export failed: {e}", at=utc_now()))
                return
            msg = f"Exported markdown → {app_path}"
            if obs_path is not None:
                msg += f" · Obsidian → {obs_path}"
            elif self.settings.obsidian_meetings_dir is not None:
                tpl = self.settings.obsidian_meeting_template
                if tpl is None or not tpl.is_file():
                    msg += (
                        " · Obsidian skipped: OBSIDIAN_MEETING_TEMPLATE must point to an existing file "
                        f"(got {tpl!r})"
                    )
            store.dispatch(act.NoticeRaised(message=msg, at=utc_now()))

        elif isinstance(action, act.SummarizeSessionRequested):
            st = store.get_state()
            sid = action.session_id if action.session_id is not None else st.current_session_id
            if sid is None:
                store.dispatch(
                    act.ErrorRaised(
                        message="No session to summarize. On Live tab record first; on Meetings tab select a meeting and press k.",
                        at=utc_now(),
                    )
                )
                return
            try:
                await self._session_service.summarize_session(session_id=sid)
            except KeyError:
                store.dispatch(act.ErrorRaised(message="Session not found in database.", at=utc_now()))
                return
            except Exception as e:
                store.dispatch(act.ErrorRaised(message=f"Summarize failed: {e}", at=utc_now()))
                return
            store.dispatch(act.NoticeRaised(message="Summary generated and saved to the database.", at=utc_now()))
            await self._load_sessions_catalog(store)

        elif isinstance(action, act.RecordingStopRequested):
            st = store.get_state()
            should_end_session = st.recording_status in (
                RecordingStatus.recording,
                RecordingStatus.starting,
                RecordingStatus.stopping,
            )
            sid = st.current_session_id

            task = self._record_task
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._record_task = None

            if should_end_session and sid is not None:
                try:
                    self.container.sessions.end(sid)
                except Exception:
                    pass

            await self._load_sessions_catalog(store)
