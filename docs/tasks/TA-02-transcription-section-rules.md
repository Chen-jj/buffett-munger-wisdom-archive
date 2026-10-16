# TA-02 — Implement pure transcription section rules

- **Status:** accepted
- **Module:** `transcription/domain`
- **Decision coverage:** ADR-0004 sections 3, 5, 6, 7, 8
- **Depends on:** TA-01
- **Depended on by:** TA-03

## Goal

Implement and unit-test provider-neutral rules that derive word-level effective
chapter membership, expose document-section boundary signals, and aggregate
already-complete sentences into all-or-nothing public sections.

## Exact scope

- Derive a direct chapter index from each timed word's `official_token_ids`,
  rejecting a word whose referenced official tokens cross chapters.
- Fill leading no-OT words from the first later chapter, and middle/trailing
  no-OT words from the preceding chapter. Preserve diagnostics that distinguish
  direct mapping from fallback assignment.
- Return no effective grouping when all words have no official token.
- Make chapter changes available as a forced boundary signal while allowing a
  more specific already-reliable boundary source to win at the same position.
- Aggregate complete sentences with one effective chapter each into stable
  `sec1..secN` ranges and titles selected by one-based `chapter_index`, never by
  page `chapter_number`.
- Represent every section-specific unsafe condition as a conservative
  `sections=[]` result plus diagnosable reason: unmapped spoken chapter,
  non-monotonic/jumping chapter order, cross-section sentence, bad title
  association, or incomplete/overlapping range.
- Put the section policy/version in a pure serializable value so TA-03 can bind
  it into the canonical cache key.

Prefer a new narrowly scoped domain file and its exports rather than mixing I/O
into existing sentence policy code. This task owns its new pure unit-test file.

## Non-goals

- Do not read artifacts, manifests, or checksums.
- Do not publish JSON or emit workflow events.
- Do not edit `src/transcription/application/sentences.py` or workflow files;
  those are reserved for TA-03.
- Do not split or renumber sentences during final section aggregation.

## Acceptance criteria

1. Unit tests cover one OT, multiple same-chapter OTs, and no OT.
2. Unit tests cover leading, middle, and trailing ASR-only assignment and the
   all-ASR-only empty-section case.
3. A chapter transition is surfaced at the correct word boundary.
4. Valid sentences produce stable, ordered, complete section coverage and empty
   titles remain publishable.
5. Every ADR-0004 conservative fallback case returns no partial sections and a
   specific diagnostic reason.

## Verification

```bash
python -m pytest tests/transcription/test_transcription_sections.py -q
python -m pytest tests/transcription/test_transcription_sentence_boundaries.py -q
```

- **Full offline suite required:** no; TA-03 owns the integration-wide gate
- **Live test:** no
