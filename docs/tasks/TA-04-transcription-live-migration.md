# TA-04 — Migrate the gated transcription live integration

- **Status:** accepted
- **Module:** transcription live fixture/tests
- **Decision coverage:** ADR-0004 sections 12–13; ADR-0002 section 15 step 2
- **Depends on:** TA-03A
- **Depended on by:** TA-05
- **Gate:** live; network, ffmpeg, model cache/download, and explicit opt-in

## Goal

Replace the one-chapter CNBC live sample with the required contiguous
two-chapter sample, regenerate it from an empty integration workspace, and prove
the new canonical section contract and manifest reuse against real WhisperX.

## Exact scope

- Change only transcription live fixture/test files and their documentation to
  use CNBC 2000 morning `35:01`–`45:24`, chapters 6 and 7.
- Generalize fixture selection from one requested chapter to the exact two
  ordered chapters; persist both titles and the clip/selection metadata needed
  for assertions.
- Keep generated media/model/output files gitignored and outside the source
  tree.
- From an empty live workspace, run through `source_alignment.json`; assert two
  ordered sections, exact chapter titles, continuous non-overlapping complete
  sentence coverage, and a legal chapter 6→7 boundary (including
  `document_section_change` when it is the signal that closes the sentence).
- Run a second time and assert the canonical checksum is identical and all six
  transcription layers are reused from manifest evidence.

## Safety and live gate

Clearing the existing gitignored integration workspace is required by the ADR,
but repository policy forbids deleting files without explicit user
confirmation. The assignee must obtain that confirmation before removal. Do not
substitute an uncleared workspace or silently overwrite it. The live test must
remain marked `live` and must skip unless `RUN_TRANSCRIPTION_INTEGRATION=1`.

## Non-goals

- Do not change production section algorithms to make the sample pass.
- Do not add a checked-in golden transcript or media file.
- Do not run the live test by default or claim it ran if prerequisites are
  absent.
- Do not modify translation code or public translation contracts.

## Acceptance criteria

1. Offline fixture tests prove timestamp parsing and exact ordered chapter
   selection without network access.
2. The full offline suite passes before live execution.
3. The live run starts from an explicitly confirmed empty workspace and proves
   all ADR-0004 live assertions.
4. The rerun proves manifest-driven reuse and identical canonical checksum.
5. Test documentation states the new range, chapters, prerequisites, and gate.

## Verification

```bash
python -m pytest tests/transcription/test_live_fixture.py -q
python -m pytest tests/ -q -m "not live"

# LIVE GATE — only after explicit workspace-delete confirmation and prerequisites
RUN_TRANSCRIPTION_INTEGRATION=1 \
  .venv/bin/python -m pytest tests/transcription/test_integration_live.py -q -s
```

- **Full offline suite required:** yes, before live
- **Live test:** required and explicitly gated
