# transcription AGENTS.md

## Module Purpose

`transcription` owns audio extraction, ASR, alignment, and English subtitle generation.

## Responsibilities

- Extract or locate audio from downloaded media.
- Run ASR and optional alignment to produce English segments.
- Emit timing-preserving English SRT and alignment metadata.
- Make model/device choices explicit and reproducible.

## Layering Rules

- `domain/`: audio asset, ASR segment, word timing, alignment confidence, and transcript timing policy.
- `application/`: extract-audio, transcribe-session, align-transcript, and generate-english-srt use cases.
- `infrastructure/`: ffmpeg audio extraction, faster-whisper/WhisperX adapters, model loading, and temporary file handling.
- `interfaces/`: CLI command handlers, progress reports, and orchestration-facing transcription summaries.

## Technology Direction

- Treat Whisper/Faster-Whisper/WhisperX as replaceable providers.
- Keep long-running model work outside CLI handlers.
- Persist enough metadata to explain which model and settings produced an SRT.

## Phased Goals

- Phase 1: Wrap existing English SRT generation into an application service.
- Phase 2: Add validation for monotonic timings and coverage gaps.
- Phase 3: Add provider-level tests/mocks and fixture-based subtitle regression checks.
