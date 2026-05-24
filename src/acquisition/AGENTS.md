# acquisition AGENTS.md

## Module Purpose

`acquisition` owns web page analysis, crawling, transcript extraction, and source metadata normalization.

## Responsibilities

- Analyze archive pages and discover year/session/video/transcript resources.
- Extract chapters, transcript text, speaker/session metadata, and source URLs.
- Enforce politeness rules: user agent, delay, retry, and crawl scope.
- Persist normalized acquisition artifacts that downstream modules can consume without re-crawling.

## Layering Rules

- `domain/`: source page, crawl target, transcript section, chapter, and normalized metadata concepts.
- `application/`: crawl-year, crawl-session, refresh-metadata, and validate-source use cases.
- `infrastructure/`: HTTP clients, BeautifulSoup parsers, site-specific CNBC/archive adapters, and local artifact writers.
- `interfaces/`: CLI command handlers, crawl result DTOs, and orchestration-facing summaries.

## Technology Direction

- Use `requests` and `beautifulsoup4` initially; hide both behind infrastructure adapters.
- Site-specific parsing must not leak into downstream modules.
- Store raw source references and normalized outputs separately when practical.

## Phased Goals

- Phase 1: Extract crawler contracts from legacy `step0` behavior.
- Phase 2: Add source-specific parser tests using saved HTML fixtures.
- Phase 3: Support additional Buffett/Munger sources by adding adapters, not new pipeline branches.
