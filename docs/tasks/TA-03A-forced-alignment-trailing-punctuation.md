# TA-03A — Restore provider-dropped trailing punctuation surfaces

- **Status:** accepted
- **Module:** transcription forced-alignment provider adapter
- **Decision coverage:** unblocks ADR-0004 section 13 live acceptance without weakening ADR-0001 alignment invariants
- **Depends on:** TA-03
- **Depended on by:** TA-04

## Goal

Handle the provider-neutral case observed in the TA-04 live sample where raw ASR
contains a lexical token such as `figures—` but WhisperX returns the acoustically
aligned candidate `figures`. Restore the exact raw ASR surface in the WhisperX
adapter only when the adapter can prove that the provider omitted trailing
punctuation and preserved all lexical content.

## Exact scope

- In `WhisperXForcedAligner`, compare each flattened provider candidate with its
  corresponding raw ASR token before creating the `AlignmentCandidate`.
- Permit restoration only when all of the following are true:
  - candidate count, raw word ID, segment ID, and position already correspond;
  - the provider candidate is an exact prefix of the raw surface;
  - the remaining raw suffix is non-empty trailing punctuation containing no
    lexical/alphanumeric content;
  - removing only that trailing punctuation from the raw surface yields the
    provider candidate exactly.
- For that narrow case, set the candidate surface to the **exact original raw
  token**, including its original Unicode punctuation. Keep the provider's
  start/end timing, alignment score, and aligned/unaligned state unchanged.
- Keep the application/domain equality check strict. The fix belongs at the
  provider normalization boundary; do not make
  `resolve_alignment_candidates()` ignore punctuation or otherwise accept a
  different candidate surface.
- Add offline regression coverage at all three affected levels:
  - adapter: `figures—` + provider `figures` restores `figures—`, including its
    original timing and score;
  - domain/application gate: lexical changes, leading/internal punctuation
    changes, reordered/missing/extra candidates, or an alphanumeric suffix still
    fail the existing strict invariants;
  - workflow: the restored raw surface reaches `aligned_asr.json` and downstream
    source alignment without changing token count/order or requiring
    interpolation.
- Include representative ASCII and Unicode trailing punctuation cases, plus
  negative cases that prove this is not general fuzzy matching.

Primary ownership for this task:

- `src/transcription/infrastructure/audio_asr.py`
- `tests/transcription/test_transcription_forced_alignment.py`
- the smallest necessary workflow regression in
  `tests/transcription/test_transcription_workflow.py`

## Non-goals

- Do not change raw ASR tokenization or rewrite `raw_asr.json`.
- Do not strip punctuation from canonical output; canonical text must retain the
  exact raw surface.
- Do not relax candidate count, order, raw-word/segment identity, lexical
  equality, timing bounds, non-overlap, alignment-score, or interpolation
  gates.
- Do not accept case changes, spelling changes, leading/internal punctuation
  differences, or any suffix containing lexical/alphanumeric content.
- Do not special-case the literal word `figures`, the em dash character, CNBC,
  or the live fixture.
- Do not edit section generation, translation, or live-fixture expectations.

## Acceptance criteria

1. The WhisperX adapter restores `figures—` from a provider candidate
   `figures`, preserving the exact Unicode raw surface, provider timing, and
   score.
2. The restored candidate passes the unchanged strict application/domain
   surface equality and produces no interpolation.
3. Candidate count and order remain exactly the raw token count and order.
4. Negative tests prove lexical substitutions and all non-trailing-punctuation
   differences still fail; timing and score gates remain unchanged.
5. An offline workflow regression persists the restored surface through the
   canonical chain.
6. The entire offline repository test suite passes before TA-04 resumes.

## Verification

```bash
python -m pytest tests/transcription/test_transcription_forced_alignment.py -q
python -m pytest tests/transcription/test_transcription_workflow.py -q
python -m pytest tests/transcription/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
```

- **Full offline suite required:** yes
- **Live test:** no; TA-04 owns the resumed gated live run
