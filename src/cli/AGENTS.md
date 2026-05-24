# cli AGENTS.md

## Module Purpose

`cli` owns human-facing command structure and connects user commands to application use cases.

## Responsibilities

- Parse command-line options and validate user intent.
- Invoke application services from modules without embedding business rules.
- Provide progress, dry-run, confirmation, and error messages suitable for long-running local jobs.
- Preserve compatibility with existing CLI workflows during migration.

## Layering Rules

- `domain/`: generally empty unless CLI-specific command concepts are needed.
- `application/`: command composition that spans one user action but delegates business work to feature modules.
- `infrastructure/`: terminal output, prompt/confirmation helpers, and environment discovery.
- `interfaces/`: argparse/Typer/click command definitions and command DTO mapping.

## Technology Direction

- `argparse` is acceptable for the near term; consider Typer only if command complexity grows.
- CLI must depend on application services, not on parser/downloader/ffmpeg provider implementations directly.
- Long-running commands should support dry-run and explicit overwrite/resume policy.

## Phased Goals

- Phase 1: Group existing commands by capability module.
- Phase 2: Move monolithic CLI logic into thin command handlers.
- Phase 3: Add command smoke tests for help text and argument validation.
