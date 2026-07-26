# orchestration AGENTS.md

## Module Purpose

`orchestration` owns multi-step workflow composition, dependency ordering, resumability, and failure recovery policy.

## Responsibilities

- Compose acquisition, download, transcription, translation, rendering, review, and Web catalog workflows.
- Decide what can be skipped, resumed, retried, or invalidated based on manifests and inputs.
- Provide pipeline plans that can be executed by CLI or future automation.
- Keep orchestration free of provider-specific implementation details.

## Layering Rules

- `domain/`: pipeline stage, task dependency, execution plan, artifact requirement, and recovery policy concepts.
- `application/`: run-year, run-session, resume-pipeline, plan-pipeline, and verify-readiness use cases.
- `infrastructure/`: local lock files, manifest persistence, and optional process scheduling helpers.
- `interfaces/`: CLI-facing plan summaries and machine-readable workflow reports.

## Technology Direction

- Start with synchronous local execution; do not introduce queues or services prematurely.
- Make every stage explicit and inspectable before execution.
- Prefer manifest-driven decisions over checking only file existence.
- When composing acquisition crawlers, register source-specific crawlers first
  (`CnbcCrawler`, `YoutubeCrawler`, etc.) and keep `GenericCrawler` last. The
  generic crawler is an intentional fallback whose `accepts()` may match broadly,
  and `DefaultCrawlerRegistry` selects the first accepting crawler.

## Phased Goals

- Phase 1: Re-express legacy `run.py` flow as a plan over module use cases.
- Phase 2: Add resumable session-level execution.
- Phase 3: Add parallelism only where artifact dependencies and external limits are well understood.
