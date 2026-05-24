# media_download AGENTS.md

## Module Purpose

`media_download` owns media URL resolution, video/audio download workflows, and downloaded artifact provenance.

## Responsibilities

- Resolve playable media URLs from acquisition metadata or source pages.
- Plan and execute downloads through downloader adapters.
- Capture format, size, checksum, source URL, retry count, and download timestamp metadata.
- Provide idempotent behavior for existing media assets.

## Layering Rules

- `domain/`: media source, requested format, downloaded asset, download policy, and provenance concepts.
- `application/`: resolve-media, download-session-video, verify-download, and resume-download use cases.
- `infrastructure/`: `yt-dlp` adapter, HTTP probing, filesystem writes, and checksum calculation.
- `interfaces/`: CLI command handlers, progress events, and orchestration-facing download results.

## Technology Direction

- Use `yt-dlp` as the default adapter, isolated behind a port.
- Use `ffprobe` only for verification metadata, not as a business-rule dependency.
- Prefer resumable and explicit overwrite behavior.

## Phased Goals

- Phase 1: Preserve current download behavior behind a clean application service.
- Phase 2: Add manifest-based skip/resume decisions.
- Phase 3: Support alternate download providers through adapter registration.
