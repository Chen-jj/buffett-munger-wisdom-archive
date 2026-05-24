# webui AGENTS.md

## Module Purpose

`webui` owns the local review UI integration boundary and presentation contracts for generated assets.

## Responsibilities

- Define the catalog contract consumed by the static review UI.
- Serve or prepare local review assets without owning media-processing logic.
- Present years, sessions, chapters, video files, subtitles, and review findings.
- Keep browser-specific concerns separate from pipeline modules.

## Layering Rules

- `domain/`: only UI-neutral concepts if needed, such as view-ready catalog constraints.
- `application/`: prepare-review-site, validate-catalog-contract, and resolve-static-assets use cases.
- `infrastructure/`: local HTTP server, static file copying, and existing `webapp/` integration adapters.
- `interfaces/`: Web DTOs, JSON schema-like contracts, and CLI-facing serve commands.

## Technology Direction

- Continue with lightweight static HTML/CSS/JS unless requirements justify a frontend build stack.
- Treat root `webapp/` as the current static implementation and `src/webui` as its Python integration boundary.
- Keep generated catalog schemas stable and documented.

## Phased Goals

- Phase 1: Define catalog schema and serving boundary.
- Phase 2: Move server/catalog glue out of monolithic CLI code.
- Phase 3: Add contract tests for catalog compatibility with the static app.
