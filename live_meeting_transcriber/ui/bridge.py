from __future__ import annotations

from live_meeting_transcriber.domain import application_events as ev
from live_meeting_transcriber.ui.state import actions as act
from live_meeting_transcriber.ui.state.model import TranscriptionStatus


def application_events_to_actions(event: ev.ApplicationEvent) -> tuple[act.Action, ...]:
    """Map domain/application events to UI actions (no I/O)."""
    out: list[act.Action] = []

    if isinstance(event, ev.RecordingLoopEntered):
        out.append(act.AudioSourceChanged(source=event.audio_source, at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.AudioChunkCaptured):
        pass

    elif isinstance(event, ev.AudioChunkLevelMeasured):
        out.append(act.AudioLevelUpdated(level=event.peak_linear, at=event.at))

    elif isinstance(event, ev.AudioChunkSkippedSilent):
        # Normal operation, not a fault: keep status active so quiet stretches don't
        # read as a stall, and feed the empty-chunk counter so sustained silence still
        # surfaces the low-audio/misrouted-source hint. The chunk still *happened*, so
        # the F8 per-chunk counter advances too (silence must not look like a stall).
        out.append(act.TranscriptionChunkEmptyObserved(at=event.at))
        out.append(act.ChunkProcessingFinished(at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.TranscriptionChunkStarted):
        out.append(act.ChunkProcessingStarted(at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.TranscriptionChunkCompleted):
        out.append(act.ChunkProcessingFinished(at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.TranscriptionChunkEmpty):
        # Not an error, but track it: repeated empties mean silent/misrouted audio and
        # the reducer surfaces a one-time hint. Keep transcription status active.
        out.append(act.TranscriptionChunkEmptyObserved(at=event.at))
        out.append(act.ChunkProcessingFinished(at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.TranscriptionChunkFailed):
        out.append(
            act.WarningRaised(
                message=f"Transcription skipped for chunk: {event.message}", at=event.at
            )
        )
        out.append(act.ChunkProcessingFinished(at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.active, at=event.at))

    elif isinstance(event, ev.TranscriptionUnavailable):
        out.append(act.WarningRaised(message=event.message, at=event.at))
        out.append(act.TranscriptionStatusChanged(status=TranscriptionStatus.degraded, at=event.at))

    elif isinstance(event, ev.DiarizationChunkCompleted):
        # Speaker is already set on each TranscriptSegmentPersisted; avoid
        # DiarizationSegmentReceived which only touched the last line and could
        # desync the RichLog from reducer state.
        clean = frozenset(s for s in event.detected_speakers if s and s != "unknown")
        if clean:
            out.append(act.DiarizationSpeakersDetected(speakers=clean, at=event.at))

    elif isinstance(event, ev.ScreenCaptureShotTaken):
        out.append(act.ScreenCaptureShotObserved(shot_count=event.shot_count, at=event.at))

    elif isinstance(event, ev.ScreenCaptureUnavailable):
        out.append(act.WarningRaised(message=event.message, at=event.at))

    elif isinstance(event, ev.DiarizationFailed):
        out.append(act.WarningRaised(message=f"Diarization: {event.message}", at=event.at))

    elif isinstance(event, ev.TranscriptSegmentPersisted):
        seg = event.segment
        out.append(
            act.TranscriptSegmentReceived(
                segment_id=str(seg.id),
                session_id=str(seg.session_id),
                started_at=seg.started_at,
                ended_at=seg.ended_at,
                text=seg.text,
                speaker=seg.speaker,
                at=event.at,
            )
        )

    elif isinstance(event, ev.RecordingStopped):
        out.append(act.RecordingStopped(at=event.at))

    elif isinstance(event, ev.RecordingFailed):
        out.append(act.RecordingFailed(message=event.message, at=event.at))

    elif isinstance(event, ev.SessionCreated):
        # Session lifecycle is driven by effects; UI RecordingStarted is dispatched there with full fields.
        pass

    elif isinstance(event, ev.RecordingPrepareStarted):
        pass

    elif isinstance(event, ev.RecordingStopRequested):
        out.append(act.RecordingStopRequested(at=event.at))

    return tuple(out)
