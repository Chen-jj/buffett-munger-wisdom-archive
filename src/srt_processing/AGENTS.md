# srt_processing AGENTS.md

## Module Purpose

`srt_processing` owns subtitle structure, SRT parsing/writing, timing-preserving transformations, bilingual composition, and subtitle QA.

## Responsibilities

- Parse, normalize, split, merge, and write SRT while preserving sequence and timing.
- Validate subtitle numbering, timestamp monotonicity, overlaps, empty entries, and duration anomalies.
- Compose bilingual subtitle representations without coupling to rendering style.
- Provide reusable text segmentation utilities for translation and review.

## Layering Rules

- `domain/`: subtitle cue, time range, subtitle document, validation finding, and transform policy.
- `application/`: validate-srt, repair-structure, merge-bilingual, split-for-translation, and compare-subtitles use cases.
- `infrastructure/`: `pysubs2` adapter and filesystem codecs.
- `interfaces/`: CLI handlers, review DTOs, and rendering/translation-facing contracts.

## Technology Direction

- Use `pysubs2` as an adapter, not as the domain model.
- Keep translation provider calls out of this module; this module prepares and validates text units only.
- Keep ASS styling out of this module; rendering owns presentation styles.

## Phased Goals

- Phase 1: Define canonical subtitle document and validation findings.
- Phase 2: Move reusable SRT checks out of CLI/rendering code.
- Phase 3: Add fixture tests for malformed, bilingual, and long-duration subtitles.
