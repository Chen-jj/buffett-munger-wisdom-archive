# AGENTS.md

## Project Overview

- Name: `buffett-munger-wisdom-archive`
- Stack: Python 3 CLI/media pipeline, `requests`/`beautifulsoup4` crawling, `yt-dlp` download, `ffmpeg`/`ffprobe` media processing, Whisper/WhisperX-style ASR alignment, OpenAI-compatible translation, `pysubs2` subtitle conversion, lightweight static Web review UI.
- Description: An offline media-asset pipeline for collecting Buffett and Munger related public videos, extracting archive metadata and transcripts, downloading source videos, producing English and Chinese subtitles, burning reviewable subtitled videos, and exposing generated assets through CLI and local Web UI workflows.
- Product boundary: The repository should optimize for reproducible local processing of long-form archive videos. It is not a general video platform, CMS, or cloud service unless such adapters are explicitly added later.

### Module Map

- `src/archive_core/` -> shared domain model, asset identity, path conventions, pipeline state, and cross-module value objects.
- `src/acquisition/` -> web page analysis, crawling, transcript extraction, source metadata normalization, and politeness rules.
- `src/media_download/` -> media URL resolution, video/audio download orchestration, checksum/provenance capture, and downloader adapters.
- `src/transcription/` -> audio extraction, ASR, word/segment alignment, and English subtitle generation.
- `src/srt_processing/` -> SRT parsing, validation, segmentation, bilingual merging, timing-preserving transforms, and subtitle QA utilities.
- `src/translation/` -> translation planning, batching, glossary/style policy, provider adapters, and translation result validation.
- `src/subtitle_rendering/` -> SRT/ASS styling, burn-in rendering, ffmpeg command planning, and render artifact metadata.
- `src/review/` -> review report generation, asset catalog building, structural checks, and human review data preparation.
- `src/webui/` -> local Web UI backend/static asset integration boundary, catalog contracts, and review-facing presentation adapters.
- `src/cli/` -> command parsing, human-facing commands, progress display, and invocation of application use cases.
- `src/orchestration/` -> pipeline composition, resumable workflows, task plans, dependency ordering, and failure recovery policy.
- `src/infrastructure/` -> shared technical adapters for config, filesystem, process execution, HTTP, logging, and external tool discovery.

## Architecture

- Organize code by capability, not by sequential step number. Step-based names are allowed only as temporary migration shims.
- Each large module follows four logical layers: `domain/`, `application/`, `infrastructure/`, and `interfaces/`.
- `domain/` contains pure business concepts and rules. It must not import network clients, CLI frameworks, `subprocess`, filesystem-heavy code, or UI code.
- `application/` contains use cases and workflow coordination inside the module. It may depend on `domain/` and abstract ports, but not on concrete external services directly.
- `infrastructure/` contains adapters for HTTP, files, ffmpeg, yt-dlp, ASR libraries, translation providers, and other external systems.
- `interfaces/` contains module-facing DTOs, command handlers, presenters, serializers, or thin integration boundaries used by CLI/Web/orchestration.
- Cross-module communication should use explicit application services, DTOs, or contracts from `archive_core`; do not import another module's infrastructure implementation directly.
- `archive_core` is the only module intended for broadly shared domain primitives. Avoid creating circular dependencies through convenience imports.
- Treat `output/<year>/<session>/` as an asset workspace with stable contracts. Any module writing files must also define expected filenames, metadata, and idempotency behavior.
- Crawling, downloading, ASR, translation, and rendering must be resumable and deterministic where practical. Prefer manifest/provenance records over implicit assumptions.
- CLI and Web UI must stay thin. They validate user input, call application services, and render results; they must not contain media-processing or crawling business logic.
- External tools and APIs must be isolated behind adapters so tests can run without network, OpenAI-compatible services, yt-dlp, or ffmpeg.
- Favor small, verifiable migrations. Do not rewrite legacy scripts wholesale unless the target module has equivalent tests or manual verification steps.
- New module work must update the nearest module `AGENTS.md` if it changes architectural intent, public contracts, or phased goals.

## Build, Test & Verify

- Install: `python3.11 -m venv .venv && . .venv/bin/activate && python -m pip install -r requirements.txt -r requirements-dev.txt`
- Test suite (offline): `python -m pytest tests/ -q`
- Architecture verification: `fd '^AGENTS\.md$' src --max-depth 3 | sort` and inspect module guidance before implementing.

## Critical Constraints

- Do not introduce cloud persistence, background workers, web frameworks, or databases unless a concrete workflow requires them.
- Do not put provider-specific OpenAI, Whisper, yt-dlp, or ffmpeg logic in domain or application layers.
- Do not make Web UI or CLI the owner of business rules.
- Do not assume generated subtitles are authoritative without validating sequence, timing monotonicity, and file provenance.
- Do not silently overwrite expensive generated assets; require explicit overwrite policy or resumable artifact versioning.
- Do not refactor unrelated legacy scripts while implementing a module slice.
- Never delete generated or source media assets without explicit user confirmation.

## Additional docs

- Module architecture guides live in each `src/<module>/AGENTS.md`.
- Keep `README.md` focused on user workflows; keep architectural rules in this file and module-level `AGENTS.md` files.
