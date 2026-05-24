# review AGENTS.md

## Module Purpose

`review` owns structured review data, validation reports, catalog generation, and human review preparation.

## Responsibilities

- Generate review JSON for subtitles, renders, and asset completeness.
- Build catalog data consumed by Web UI or future review tools.
- Provide structural QA findings without pretending to solve audio-level semantic review automatically.
- Track human review status and annotations if that workflow is added later.

## Layering Rules

- `domain/`: review finding, severity, asset completeness, catalog item, and review status concepts.
- `application/`: generate-review-report, build-catalog, compare-renders, and summarize-session-readiness use cases.
- `infrastructure/`: JSON writers/readers, local asset scanners, and optional static catalog emitters.
- `interfaces/`: CLI report output, Web UI catalog DTOs, and orchestration-facing readiness summaries.

## Technology Direction

- Keep review reports deterministic and machine-readable.
- Do not couple review logic to browser implementation details.
- Prefer severity-coded findings with enough context for humans to act.

## Phased Goals

- Phase 1: Formalize existing `.review.json` and catalog structures.
- Phase 2: Add subtitle/render completeness checks as reusable services.
- Phase 3: Add optional human review state without blocking batch processing.
