from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from live_meeting_transcriber.application.container import Container
from live_meeting_transcriber.application.export_overwrite import export_content_identical
from live_meeting_transcriber.application.recorder import Recorder
from live_meeting_transcriber.application.session_service import SessionService
from live_meeting_transcriber.audio.sources import resolve_microphone_source
from live_meeting_transcriber.config.device_prefs import (
    DevicePrefs,
    load_device_prefs,
    save_device_prefs,
)
from live_meeting_transcriber.config.settings import Settings
from live_meeting_transcriber.domain.application_events import ApplicationEvent
from live_meeting_transcriber.obsidian.meeting_export import (
    ExportCancelledError,
    prepare_dual_export,
    write_dual_export,
)
from live_meeting_transcriber.ui.bridge import application_events_to_actions
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import (
    RecordingStatus,
    SessionRowState,
    TranscriptLineState,
)
from live_meeting_transcriber.ui.state.store import Store
from live_meeting_transcriber.utils.time import utc_now

_MAX_LIVE_TRANSCRIPT_LINES = 200


def transcript_lines_for_session(
    container: Container,
    session_id: UUID,
    *,
    max_lines: int = _MAX_LIVE_TRANSCRIPT_LINES,
) -> tuple[TranscriptLineState, ...]:
    segs = container.transcripts.list_by_session(session_id)
    return tuple(
        TranscriptLineState(
            id=str(s.id),
            session_id=str(s.session_id),
            started_at=s.started_at,
            ended_at=s.ended_at,
            text=s.text,
            speaker=s.speaker,
        )
        for s in segs
    )[-max_lines:]


def _settings_loaded(settings: Settings, at: datetime) -> act.SettingsLoaded:
    return act.SettingsLoaded(
        transcription_provider=settings.transcription_provider,
        transcription_model=settings.effective_transcription_model_display(),
        summarization_provider=settings.llm_provider,
        summary_model=settings.summary_model,
        database_url=settings.database_url,
        audio_chunk_seconds=settings.audio_chunk_seconds,
        audio_sample_rate=settings.audio_sample_rate,
        audio_channels=settings.audio_channels,
        audio_stereo_mode=settings.audio_stereo_mode,
        diarization_enabled=settings.diarization_enabled,
        diarization_provider=settings.diarization_provider,
        finalize_on_session_stop=settings.finalize_on_session_stop,
        whisperx_model=settings.whisperx_model,
        whisperx_skip_alignment=settings.whisperx_skip_alignment,
        hf_token_configured=bool(settings.hf_token and settings.hf_token.strip()),
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
    confirm_export_overwrite: Callable[[Path], Awaitable[bool]] | None = field(
        default=None, repr=False
    )
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

    async def _finalize_session_background(self, session_id: UUID) -> None:
        await self._run_finalize_for_session(self.store, session_id)

    async def _run_finalize_for_session(self, store: Store, session_id: UUID) -> None:
        from live_meeting_transcriber.application.finalize_service import finalize_session_offline

        loop = asyncio.get_running_loop()

        def _progress(msg: str) -> None:
            def _emit() -> None:
                store.dispatch(
                    act.UiLogLineAdded(
                        level="info",
                        message=f"Finalize: {msg}",
                        at=utc_now(),
                    )
                )

            loop.call_soon_threadsafe(_emit)

        store.dispatch(
            act.UiLogLineAdded(
                level="info",
                message=f"Starting speaker ID / finalize for session {session_id}…",
                at=utc_now(),
            )
        )
        try:
            n = await finalize_session_offline(
                container=self.container,
                settings=self.settings,
                session_id=session_id,
                progress=_progress,
            )
        except ImportError as e:
            store.dispatch(
                act.ErrorRaised(
                    message=f"Speaker ID / finalize skipped: install whisperx extra ({e}).",
                    at=utc_now(),
                )
            )
            return
        except FileNotFoundError as e:
            store.dispatch(
                act.ErrorRaised(
                    message=f"No recorded audio for finalize yet: {e}",
                    at=utc_now(),
                )
            )
            return
        except Exception as e:
            store.dispatch(act.ErrorRaised(message=f"Finalize failed: {e}", at=utc_now()))
            return

        st = store.get_state()
        live_lines: tuple[TranscriptLineState, ...] | None = None
        if st.current_session_id == session_id and st.recording_status == RecordingStatus.recording:
            segs = self.container.transcripts.list_by_session(session_id)
            live_lines = tuple(
                TranscriptLineState(
                    id=str(s.id),
                    session_id=str(s.session_id),
                    started_at=s.started_at,
                    ended_at=s.ended_at,
                    text=s.text,
                    speaker=s.speaker,
                )
                for s in segs
            )[-_MAX_LIVE_TRANSCRIPT_LINES:]

        store.dispatch(
            act.FinalizeSessionSucceeded(
                session_id=session_id,
                segment_count=n,
                live_lines=live_lines,
                at=utc_now(),
            )
        )
        await self._load_sessions_catalog(store)

    async def _load_sessions_catalog(self, store: Store) -> None:
        try:
            sessions = self.container.sessions.list()
        except Exception as e:
            store.dispatch(act.ErrorRaised(message=f"Failed to list sessions: {e}", at=utc_now()))
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
            prefs = load_device_prefs()
            if prefs.monitor_source or prefs.microphone_source:
                # Seed state from persisted selection (no save effect on plain dispatch).
                store.dispatch(
                    act.AudioSourcesSelected(
                        monitor_source=prefs.monitor_source,
                        microphone_source=prefs.microphone_source,
                        at=action.at,
                    )
                )
            store.dispatch(act.SessionsRefreshRequested(at=utc_now()))
            await self._load_sessions_catalog(store)

        elif isinstance(action, act.AudioSourcesSelected):
            # Persist the UI-chosen devices so they survive restarts.
            save_device_prefs(
                DevicePrefs(
                    monitor_source=action.monitor_source,
                    microphone_source=action.microphone_source,
                )
            )

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
                        act.RecordingFailed(
                            message="Session not found; cannot continue recording.", at=utc_now()
                        )
                    )
                    return
                session = self.container.sessions.reopen(action.resume_session_id)
                if session is None:
                    store.dispatch(
                        act.RecordingFailed(
                            message="Could not reopen session for recording.", at=utc_now()
                        )
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

            mic = resolve_microphone_source(
                self.settings,
                self.container.devices,
                cli_explicit=action.microphone_source,
            )
            if self.settings.audio_include_microphone and mic is None:
                store.dispatch(
                    act.WarningRaised(
                        message="Microphone mix requested but no default mic found; "
                        "set AUDIO_MICROPHONE_SOURCE or use monitor-only (AUDIO_INCLUDE_MICROPHONE=false).",
                        at=utc_now(),
                    )
                )

            chunk_seconds = self.settings.audio_chunk_seconds
            resumed = action.resume_session_id is not None
            loaded_lines = (
                transcript_lines_for_session(self.container, session.id) if resumed else ()
            )
            store.dispatch(
                act.RecordingStarted(
                    session_id=session.id,
                    title=session.title,
                    audio_source=source,
                    microphone_source=mic,
                    chunk_seconds=chunk_seconds,
                    at=utc_now(),
                    resumed=resumed,
                    loaded_transcript_segments=loaded_lines,
                )
            )
            aliases = self.container.session_speakers.get_map(session.id)
            store.dispatch(act.SpeakerAliasesLoaded(aliases=dict(aliases), at=utc_now()))

            chunk_dir = (self.settings.ensure_data_dir() / "chunks" / str(session.id)).resolve()
            recorder = Recorder(
                audio=self.container.audio,
                transcriber=self.container.transcriber,
                transcripts=self.container.transcripts,
                keep_audio_chunks=self.settings.keep_audio_chunks,
                chunk_output_dir=chunk_dir,
                data_dir=self.settings.ensure_data_dir(),
                audio_stereo_mode=self.settings.audio_stereo_mode,
                transcription_provider=self.settings.transcription_provider,
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

        elif isinstance(action, act.FinalizeSessionRequested):
            await self._run_finalize_for_session(store, action.session_id)

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
                store.dispatch(
                    act.ErrorRaised(message="Session not found in database.", at=utc_now())
                )
                return
            segments = self.container.transcripts.list_by_session(sid)
            summary = self.container.summaries.get_by_session(sid)
            spk = self.container.session_speakers.get_map(sid)
            export_kwargs = dict(
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
            prepared = prepare_dual_export(**export_kwargs)
            targets = [(prepared.app_path, prepared.app_content)]
            if prepared.obs_path is not None and prepared.obs_content is not None:
                targets.append((prepared.obs_path, prepared.obs_content))
            if self.confirm_export_overwrite is not None:
                for path, content in targets:
                    if (
                        path.is_file()
                        and not export_content_identical(path.read_text(encoding="utf-8"), content)
                        and not await self.confirm_export_overwrite(path)
                    ):
                        store.dispatch(act.NoticeRaised(message="Export cancelled.", at=utc_now()))
                        return
            try:
                result = write_dual_export(**export_kwargs, confirm_overwrite=lambda _: True)
            except ExportCancelledError as e:
                store.dispatch(act.ErrorRaised(message=f"Export cancelled: {e.path}", at=utc_now()))
                return
            except Exception as e:
                store.dispatch(act.ErrorRaised(message=f"Export failed: {e}", at=utc_now()))
                return
            msg = f"Exported markdown → {result.app_path}"
            if result.obs_path is not None:
                msg += f" · Obsidian → {result.obs_path}"
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
                summary = await self._session_service.summarize_session(
                    session_id=sid,
                    user_context=action.user_context,
                )
            except KeyError:
                store.dispatch(
                    act.ErrorRaised(message="Session not found in database.", at=utc_now())
                )
                return
            except Exception as e:
                store.dispatch(act.ErrorRaised(message=f"Summarize failed: {e}", at=utc_now()))
                return
            session = self.container.sessions.get(sid)
            msg = "Summary generated and saved to the database."
            if session is not None and summary.meeting_metadata is not None:
                title = summary.meeting_metadata.confident_str("title")
                if title and session.title == title:
                    msg += f" Title: {session.title}."
            store.dispatch(
                act.NoticeRaised(
                    message=msg,
                    at=utc_now(),
                )
            )
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
                if self.settings.finalize_on_session_stop:
                    asyncio.create_task(self._finalize_session_background(sid))  # noqa: RUF006

            await self._load_sessions_catalog(store)
