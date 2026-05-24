# archive_core AGENTS.md

## Module Purpose

`archive_core` owns repository-wide domain primitives and contracts that every other module can safely share.

## Responsibilities

- Define asset identity: year, session, source page, media item, transcript, subtitle, render, and review artifact concepts.
- Define stable path and naming policies for `input/`, `output/<year>/<session>/`, and generated sidecar metadata.
- Define pipeline status, provenance, checksum, overwrite, and resumability concepts.
- Provide pure validation rules that are independent of HTTP, ffmpeg, OpenAI-compatible APIs, or Web UI concerns.

## Layering Rules

- `domain/`: value objects, entities, validation policies, naming rules, and artifact state transitions.
- `application/`: shared use cases only when they are truly cross-cutting, such as resolving an asset workspace or validating an artifact manifest.
- `infrastructure/`: minimal shared adapters for reading/writing core manifests if they are not specific to one feature module.
- `interfaces/`: DTOs and serializers used by CLI, Web UI, review, and orchestration.

## Technology Direction

- Prefer dataclasses or small typed objects for domain concepts.
- Keep serialization explicit and versioned; avoid leaking raw dictionaries across modules.
- Avoid heavy dependencies in this module.

## Phased Goals

- Phase 1: Document asset identifiers, canonical filenames, and metadata contracts.
- Phase 2: Move shared path/provenance logic out of legacy scripts.
- Phase 3: Add focused tests for path rules and manifest compatibility.
