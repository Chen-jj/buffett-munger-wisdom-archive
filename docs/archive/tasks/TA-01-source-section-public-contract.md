# TA-01 — Publish source section contract

- **Status:** accepted
- **Module:** `archive_core`
- **Decision coverage:** ADR-0004 sections 4, 6, 10, 12, 13
- **Depends on:** none
- **Depended on by:** TA-02

## Goal

Extend the public `transcription.source-alignment.v1` contract with mandatory
`sections` and the `document_section_change` boundary source, without accepting
legacy JSON that omits `sections`.

## Exact scope

- Add `SourceSectionDTO` with exactly `id`, `title`, `first_sentence_id`, and
  `last_sentence_id`.
- Add mandatory `sections` to `SourceAlignmentDTO` serialization and parsing.
- Validate `sec1..secN`, referenced sentence IDs, source order, non-overlap, and
  either empty sections or complete exactly-once sentence coverage.
- Allow an empty section title but reject invalid field types and unknown schema
  versions. Keep `SOURCE_ALIGNMENT_SCHEMA_VERSION` unchanged.
- Add `BoundarySource.DOCUMENT_SECTION_CHANGE` and export the new public type.
- Update only the public-contract tests needed to prove these rules. Adapt all
  existing source-alignment fixtures to provide `sections=[]` explicitly.

Expected core ownership for this task:

- `src/archive_core/interfaces/transcription.py`
- `src/archive_core/interfaces/__init__.py`
- `tests/transcription/test_archive_core_transcription_contracts.py`
- any directly broken archive-core contract fixture/test

## Non-goals

- Do not calculate effective chapter indexes or create sections from chapters.
- Do not modify transcription workflow/cache/event behavior.
- Do not add translation result or manifest types.
- Do not add a missing-`sections` compatibility default.

## Acceptance criteria

1. Valid empty and multi-section alignments round-trip with `sections` always
   present in JSON.
2. Missing `sections` is rejected.
3. Duplicate/unstable section IDs, unknown sentence IDs, gaps, overlap,
   backwards ranges, and incomplete non-empty coverage are rejected.
4. An empty title is accepted.
5. Existing sentence/word invariants remain enforced and all offline tests pass.

## Verification

```bash
python -m pytest tests/transcription/test_archive_core_transcription_contracts.py -q
python -m pytest tests/archive_core/ -q
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no
