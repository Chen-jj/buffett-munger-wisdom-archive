# TA-07 — Implement translation workflow, checkpoints, and interfaces

- **Status:** accepted
- **Module:** translation application/interfaces/local infrastructure
- **Decision coverage:** ADR-0002 sections 3, 5, 6.1, 8–15 step 4
- **Depends on:** TA-06
- **Depended on by:** TA-08

## Goal

Implement the provider-neutral translation workflow end to end with fake
providers: validate canonical transcription input, execute serial fail-fast
requests, recover from strict private checkpoints, and atomically publish the
public result/manifest pair.

## Exact scope

- Define `TranslationProvider` and narrow checksum/artifact/prompt/glossary/
  checkpoint/sleeper ports in application code.
- Add stable `TranslationCommand`, `TranslationOutcome`, and command handler
  interfaces with ADR-specified fields; do not expose provider SDK responses.
- Validate transcription manifest schema, succeeded workflow, asset identity,
  canonical source-alignment path, size, actual SHA-256, and the complete public
  `SourceAlignmentDTO`; accept only English.
- Load and checksum the versioned prompt and optional glossary, then use TA-06 to
  plan ordered section/document requests.
- Reuse a checkpoint only after validating its private schema, cache key,
  request checksum, and complete response correspondence. Corruption/conflict
  fails rather than being overwritten. `overwrite=true` skips all checkpoints
  and authorizes replacement of only the same key.
- Execute requests serially and fail fast. Retry only declared transient errors,
  with total attempts bounded by `max_attempts`, `Retry-After` preferred and
  injected 2/4-second fallback sleeper. Reuse the byte-equivalent logical call.
- Atomically persist each validated checkpoint; never persist rejected,
  incomplete, invalid, or raw unscreened responses.
- Assemble deterministic public result/manifest bytes and publish them as a pair.
  On any failure, publish neither; on overwrite failure, preserve the old valid
  pair. A valid matching pair returns `reused` with zero provider calls.
- Add local JSON/checksum/atomic-publication adapters needed by this workflow,
  but no provider-specific network adapter.
- Log only the metadata allowlist from ADR-0002 section 12.

Primary ownership includes new files under `src/translation/application/`,
`src/translation/interfaces/`, provider-neutral local store code under
`src/translation/infrastructure/`, their package exports, and offline workflow
tests. TA-08 must not edit these files except a narrowly reviewed export if
unavoidable.

## Non-goals

- Do not import OpenAI or classify SDK exceptions; TA-08 owns that adapter.
- Do not read `chapters.json`, fusion artifacts, SRT, asset source, or timing.
- Do not add concurrency, locks, dry-run, model repair, token preflight, cost
  calculation, or content-quality heuristics.
- Do not update root/module status documentation yet.

## Acceptance criteria

1. Fake-provider workflow publishes a fully validated result/manifest with
   stable bytes, checksum evidence, and correct request/attempt/usage counts.
2. `timeout -> 429 -> success` makes exactly three identical calls; every
   permanent/refused/incomplete/invalid/business-validation error does not retry.
3. A section failure stops later calls and publishes no new canonical pair, but
   retains earlier valid checkpoints.
4. Resume calls only missing checkpoints; overwrite calls all requests; a
   matching formal result returns `reused` with zero provider calls.
5. Corrupt/stale checkpoints and result/manifest conflicts fail explicitly.
6. Simulated atomic write/overwrite failures preserve the prior valid pair.
7. Full offline repository tests pass.

## Verification

```bash
python -m pytest tests/translation/test_translation_application.py -q
python -m pytest tests/translation/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no
