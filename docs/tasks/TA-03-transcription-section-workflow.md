# TA-03 — Integrate sections into transcription publication

- **Status:** accepted
- **Module:** `transcription/application` and transcription interfaces
- **Decision coverage:** ADR-0004 sections 6–13
- **Depends on:** TA-02
- **Depended on by:** TA-04

## Goal

Wire TA-02's pure rules into sentence recovery and canonical publication so a
validated structured transcript produces reliable sections, while any
section-only failure publishes `sections=[]` without weakening existing word or
sentence gates.

## Exact scope

- Pass the already validated `OfficialTranscriptInput` (structured transcript
  and checksum) from `TranscriptionWorkflow` into the sentence/canonical stage.
- In the official path, verify its checksum equals
  `TranscriptFusionArtifact.chapters_sha256`; reject an invalid checksum chain.
- Compute effective chapter membership before sentence construction and force a
  verified `document_section_change` boundary only when structure actually
  creates the boundary.
- After sentence recovery, create sections through TA-02 and round-trip the
  complete public `SourceAlignmentDTO` before publication.
- Preserve document-change sentence boundaries if later section aggregation
  conservatively falls back to `[]`; never rerun or mutate sentence recovery.
- Add the section policy/version and chapter input checksum to the source
  alignment cache key/provenance. Existing audio/VAD/raw-ASR/alignment caches
  must remain reusable.
- Add stable events/findings covering direct/fallback assignment, document
  boundary, unmapped/non-monotonic/cross-section/publication-skipped, and
  published outcomes. Keep event details JSON-scalar and non-sensitive.
- Update existing workflow and sentence tests, including at least one complete
  two-chapter offline workflow proving the transition, titles, coverage, cache
  staleness, and reuse.

Primary shared-file ownership for this task:

- `src/transcription/application/sentences.py`
- `src/transcription/application/workflow.py`
- `src/transcription/application/observability.py`
- relevant `__init__.py` exports
- transcription sentence/workflow/observability offline tests

## Non-goals

- Do not change acquisition parsing, audio, VAD, raw ASR, or forced alignment.
- Do not update live fixture timestamps/chapters; TA-04 owns live files.
- Do not implement translation.
- Do not turn a core word/sentence invariant failure into a section fallback.

## Acceptance criteria

1. A two-chapter workflow publishes two ordered titled sections covering every
   sentence once; the transition is a legal sentence boundary.
2. Identity/YouTube-style inputs publish `sections=[]` and keep existing
   boundary behavior.
3. All section-only invalid states publish `sections=[]` with a finding, while
   invalid core timeline/text data still fails the stage.
4. Old canonical cache entries are stale because the new cache key includes
   section policy and chapter checksum; valid expensive upstream records reuse.
5. Second offline workflow execution reuses the new source alignment and all
   existing transcription offline tests pass.

## Verification

```bash
python -m pytest tests/transcription/test_transcription_sections.py -q
python -m pytest tests/transcription/test_transcription_sentence_boundaries.py -q
python -m pytest tests/transcription/test_transcription_observability.py -q
python -m pytest tests/transcription/test_transcription_workflow.py -q
python -m pytest tests/transcription/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no
