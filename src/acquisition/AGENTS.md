# acquisition AGENTS.md

## Module Purpose

`acquisition` owns source discovery, fetching, source-page parsing, transcript extraction, source metadata normalization, and persistence of acquisition artifacts.

## Current Architecture

- `domain/`: source-neutral value objects only: `AcquisitionRequest`, `AcquisitionTarget`, `MediaReference`, `Chapter`, `Transcript`, `SourceMetadata`, `Provenance`, and `AcquisitionResult`.
- `application/`: source-neutral orchestration. `AcquireUseCase` accepts one `AcquisitionRequest`, selects a crawler through `CrawlerRegistry`, discovers targets, fetches each target, optionally persists each result, and returns a list of `AcquisitionResult`.
- `infrastructure/`: HTTP, HTML parsing, metadata extraction, transcript normalization, source crawlers, and local artifact writing.

## Dependency Rules

- Dependencies point inward: infrastructure depends on application/domain contracts; application depends on domain and Protocol ports; domain imports only pure primitives and shared `archive_core` identity values.
- Domain must not import `requests`, `bs4`, filesystem APIs, subprocess, UI, or another module's infrastructure.
- Calling layers must construct only `AcquisitionRequest`; they must not branch by CNBC year/session, YouTube URL, DOM shape, or page selectors.
- Site-specific discovery, parsing, normalization, and source quirks belong inside the corresponding crawler.

## Source Crawler Contract

Each site implements `SourceCrawler`:

- `accepts(req) -> bool`
- `discover(req) -> list[AcquisitionTarget]`
- `fetch(target) -> AcquisitionResult`

Crawler responsibilities include resource discovery, fetch planning, page parsing, media reference extraction, metadata normalization, and provenance population.

## Infrastructure Notes

- `CnbcCrawler` accepts CNBC URLs, `cnbc:<year>`, or `hints.year`; it expands a year into session targets and applies the legacy rule that skips `highlight` when full morning/afternoon sessions exist.
- `YoutubeCrawler` accepts YouTube URLs and returns an embed media reference. It does not claim transcript availability unless a future implementation can fetch one.
- `GenericCrawler` is a fallback for selector-driven HTML pages.
- `LocalAcquisitionArtifactWriter` must use `archive_core.application.build_asset_workspace(result.asset_id, root)` and write under `output/<source>_<group>_<item>/`.

## Artifact Contract

For every `AcquisitionResult`, the writer stores:

- `meta.json`: normalized `SourceMetadata`, `asset_id`, `source_ref`, and `provenance`.
- `media_ref.json`: serialized `MediaReference`.
- `transcript.txt` and `chapters.json`: only when `transcript` is available.

Writes must be atomic per file and must pre-check all planned outputs when `overwrite=False`.

## Testing Direction

- Unit tests cover domain validation, registry routing, `AcquireUseCase` orchestration, and writer file contracts.
- Offline integration tests use saved HTML fixtures and fake HTTP clients; they must not hit the network or write outside `tmp_path`.
- Live network tests must be marked `@pytest.mark.live` and skipped by default.
