# translation AGENTS.md

## Module Purpose

`translation` owns translation planning, batching, provider calls, glossary/style policy, and translated subtitle validation.

## Responsibilities

- Translate subtitle text while preserving cue count, order, and timestamps.
- Apply Buffett/Munger domain terminology, tone, and Chinese style guidelines.
- Batch requests safely and record provider/model/prompt provenance.
- Validate provider output before it becomes a downstream subtitle artifact.

## Layering Rules

- `domain/`: translation unit, glossary term, style policy, translation batch, and provider result concepts.
- `application/`: plan-translation, translate-srt, validate-translation, and retry-failed-batches use cases.
- `infrastructure/`: OpenAI-compatible client, rate limit/retry handling, prompt loading, and response parsing.
- `interfaces/`: CLI handlers, progress events, and orchestration-facing translation summaries.

## Technology Direction

- Use OpenAI-compatible APIs through an adapter so local or alternate providers can be swapped later.
- Keep prompts versioned and tied to output provenance.
- Never let translation change timing; only text content may change.

## Phased Goals

- Phase 1: Stabilize translation input/output contracts around SRT cues.
- Phase 2: Add glossary/style policy and validation for cue count mismatch.
- Phase 3: Add resumable batch translation with cached intermediate results.
