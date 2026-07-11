from __future__ import annotations

# Chunking is currently delegated to ffmpeg (-t N).
# Near-silent chunks are skipped before live transcription via an energy heuristic
# (F1): RMS measurement in wav_level.py, pure decision in application/silence.py,
# applied by the recorder after the chunk is appended to full_session.wav.
# TODO: add real-time streaming support.
