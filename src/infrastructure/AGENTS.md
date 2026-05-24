# infrastructure AGENTS.md

## Module Purpose

`infrastructure` owns shared technical adapters that are not specific enough to belong to one feature module.

## Responsibilities

- Provide config loading, logging, filesystem helpers, process execution, HTTP base clients, and external tool discovery.
- Keep cross-cutting technical behavior consistent across modules.
- Avoid becoming a dumping ground for business logic.

## Layering Rules

- `domain/`: normally empty; if a concept has business meaning, place it in `archive_core` or the relevant feature module.
- `application/`: normally minimal; shared app services are allowed only when they are genuinely technical and cross-cutting.
- `infrastructure/`: concrete implementations for config, logging, filesystem, subprocess, HTTP, and tool probing.
- `interfaces/`: small adapter-facing protocols or DTOs if needed by multiple modules.

## Technology Direction

- Keep dependencies lightweight and explicit.
- Make subprocess execution injectable so ffmpeg/yt-dlp calls can be tested without running binaries.
- Centralize config parsing, but let feature modules own feature-specific config meaning.

## Phased Goals

- Phase 1: Define shared process/config/filesystem adapter contracts.
- Phase 2: Replace duplicated subprocess and config loading code from legacy scripts.
- Phase 3: Add focused tests for command construction and error normalization.
