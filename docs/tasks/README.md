# ADR-0004 / ADR-0002 / ADR-0005 implementation task map

This directory decomposes the accepted decisions in
`docs/decisions/0004-transcription-source-sections.md`,
`docs/decisions/0002-translation-sentence-units.md`, and
`docs/decisions/0005-translation-codex-cli-chatgpt-provider.md` into
independently assignable, verifiable tasks.

## Shared rules

- Status values are `pending`, `in_progress`, `blocked`, `accepted`, and
  `superseded`. `superseded` preserves an uncompleted task whose intended work
  was replaced by a later accepted decision; it is not an acceptance result. A
  task agent changes only its own task status; the technical lead marks it
  `accepted` after reviewing the diff and test evidence.
- Before editing a module, the assignee must read its `src/<module>/AGENTS.md`
  (and `tests/transcription/AGENTS.md` for transcription tests).
- Preserve the user's existing uncommitted changes to ADR-0002, ADR-0004,
  ADR-0005, and `requirements.txt`. Do not reset, overwrite, or reformat them.
- Default verification is offline. A command marked **live gate** must never run
  merely as part of `pytest tests/ -q`; it needs the documented opt-in
  environment variable and external prerequisites.
- Generated media and model outputs remain under gitignored `output/` and are
  never committed. Deleting an existing generated workspace requires explicit
  user confirmation under the repository safety rule.
- No task may silently add backward compatibility for a `source_alignment.json`
  that lacks `sections`; both ADRs explicitly reject that shim.
- ADR-0005 adds Codex CLI without removing the accepted OpenAI Responses
  adapter. Provider selection is explicit, there is no fallback, and the two
  providers must never share checkpoints or formal artifacts across identities.
- After ADR-0005, all new real translation runs and live acceptance use only
  `codex-cli-chatgpt`. The superseded OpenAI live gate must not be run.
- The final acceptance gate is `python -m pytest tests/ -q -m "not live"`. A
  task may require this full gate even when it also has narrower tests.

## Required order and dependency graph

The order below combines ADR-0002 section 15 with ADR-0005 section 12. An arrow
means that the left task must be accepted before the right task starts.

```text
TA-01 public source-section contract
  -> TA-02 pure section derivation rules
  -> TA-03 transcription workflow/publication integration
  -> TA-03A restore provider-dropped trailing punctuation
  -> TA-04 transcription live-fixture migration [LIVE GATE]
  -> TA-05 public translation contracts
  -> TA-06 translation domain and request planning
  -> TA-07 translation application, checkpoints, publication, interfaces
  -> TA-08 OpenAI Responses adapter
  -> TA-09 configuration, module docs, status, full offline gate
       |-> TA-10 OpenAI translation integration [SUPERSEDED; terminal]
       `-> TA-11 provider-neutral generation parameters
  -> TA-12 process-runner stdin support
  -> TA-13 Codex CLI preflight and ChatGPT-auth safety
  -> TA-14 Codex CLI translation provider
  -> TA-15 explicit provider configuration, composition, and offline gate
  -> TA-16 Codex CLI translation integration [LIVE GATE]
```

There are intentionally no parallel implementation batches on this critical
path. This both follows the mandated migration sequence and prevents two agents
from editing `archive_core` exports, transcription sentence publication, or
translation package exports at the same time. Test-only investigation may run
in parallel, but it must not write shared files.

| Batch | Task | Module(s) | Depends on | Full offline suite? |
|---:|---|---|---|---:|
| 1 | [TA-01](TA-01-source-section-public-contract.md) | archive_core | none | yes |
| 2 | [TA-02](TA-02-transcription-section-rules.md) | transcription domain | TA-01 | no |
| 3 | [TA-03](TA-03-transcription-section-workflow.md) | transcription application | TA-02 | yes |
| 4 | [TA-03A](TA-03A-forced-alignment-trailing-punctuation.md) | transcription forced-alignment adapter | TA-03 | yes |
| 5 | [TA-04](TA-04-transcription-live-migration.md) | transcription live tests | TA-03A | yes, then live |
| 6 | [TA-05](TA-05-translation-public-contracts.md) | archive_core | TA-04 | yes |
| 7 | [TA-06](TA-06-translation-domain.md) | translation domain | TA-05 | no |
| 8 | [TA-07](TA-07-translation-application.md) | translation application/interfaces/local I/O | TA-06 | yes |
| 9 | [TA-08](TA-08-openai-responses-adapter.md) | translation infrastructure | TA-07 | yes |
| 10 | [TA-09](TA-09-configuration-and-status.md) | configuration/docs | TA-08 | yes |
| 11 | [TA-10](TA-10-translation-live-integration.md) | OpenAI translation live test | TA-09 | superseded; do not run |
| 12 | [TA-11](TA-11-provider-neutral-generation-parameters.md) | archive_core / translation contracts | TA-09 | yes |
| 13 | [TA-12](TA-12-process-runner-stdin.md) | infrastructure | TA-11 | yes |
| 14 | [TA-13](TA-13-codex-cli-preflight.md) | translation infrastructure | TA-12 | yes |
| 15 | [TA-14](TA-14-codex-cli-provider.md) | translation infrastructure | TA-13 | yes |
| 16 | [TA-15](TA-15-provider-configuration-composition.md) | translation configuration/composition/docs | TA-14 | yes |
| 17 | [TA-16](TA-16-codex-cli-live-integration.md) | translation live tests/final status | TA-15 | yes, then live |

## Technical-lead acceptance

For every task, review that every changed line traces to its scope, inspect the
diff for unrelated refactors, and rerun the task's commands. After TA-09 and
again after TA-15, rerun the entire offline suite. After each live-gated task,
record whether it ran,
which prerequisites were present, and the canonical checksum/cache-reuse
evidence. ADR-0002, ADR-0004, and ADR-0005 are implemented only after every
non-superseded listed task, including TA-03A and TA-11 through TA-16, is
accepted. A missing ChatGPT login, unsupported Codex CLI, or missing explicit
permission to clear a live workspace is a blocker, not permission to weaken the
gate or fall back to the OpenAI API.
