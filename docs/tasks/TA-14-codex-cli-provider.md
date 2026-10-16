# TA-14 — Implement the Codex CLI ChatGPT translation provider

- **Status:** accepted
- **Module:** `translation/infrastructure`
- **Decision coverage:** ADR-0005 sections 7–10 and 11.1–11.2
- **Depends on:** TA-13
- **Depended on by:** TA-15

## Goal

Implement `CodexCliChatGPTTranslationProvider` behind the existing provider port
with the ADR's isolated, structured, non-fallback execution and conservative
error semantics.

## Exact scope

- For each existing section/document `ProviderCall`, launch one independent
  `codex exec` with the exact required safety flags: ephemeral session, ignored
  user config, read-only sandbox, skipped repository check, fixed model, forced
  ChatGPT login, high reasoning, output schema, final-message path, isolated
  empty cwd, and stdin marker.
- Derive stdin solely from the existing instructions and canonical request JSON
  using the ADR prompt envelope. Write `call.output_schema` to the private schema
  path; do not maintain a second prompt, glossary, planner, or response schema.
- Build a child environment that retains required normal environment state but
  removes `OPENAI_API_KEY`. Never pass credentials in argv or inspect/copy Codex
  auth files.
- Accept success only for a zero exit within timeout and a final-message file
  containing exactly one JSON object with no fences, prose, or extra envelope.
  Return attempt count 1 with null usage and request ID, leaving ID/order/content
  validation to the existing application gate.
- Implement the ADR error table without internal retries. Only timeout and an
  explicit machine-readable temporary connection event are transient; unknown
  nonzero exits are permanent `cli_failed`. Map configuration, auth/API billing,
  model availability, usage limit, request size/incomplete, and malformed output
  to their specified permanent codes. Do not promote errors based on broad
  stderr substring guesses.
- Ensure public logs/errors never include stdin, request/source data, translated
  output, raw stderr, auth details, or private temporary-file content.
- Add offline fake-runner/filesystem tests for exact argv/cwd/stdin/environment,
  successful parsing, all error branches, redaction, application validation
  failures, checkpoint behavior, and provider-identity cache isolation.

## Non-goals

- Do not modify provider-neutral ports, workflow retry/fail-fast logic, request
  boundaries, checkpoints, or publication rules.
- Do not automatically invoke OpenAI, mix providers in one result, use a shell,
  use a repository working directory, or bypass sandbox/approval controls.
- Do not run the real Codex CLI or network in this task.

## Acceptance criteria

1. Tests prove exact secure invocation and exact envelope/schema derivation for
   one process per existing request.
2. API-key environment data cannot reach the child and ambiguous auth/error
   output cannot be treated as success or a retryable failure.
3. Successful output reaches the unchanged application validation; invalid or
   partial output never writes a checkpoint or formal artifact.
4. OpenAI and Codex identities cannot reuse each other's checkpoints or formal
   artifacts, and the existing OpenAI adapter remains unchanged and passing.
5. The complete offline suite passes without real Codex/network access.

## Verification

```bash
python -m pytest tests/translation/ -q -m "not live" -k "codex"
python -m pytest tests/translation/ -q -m "not live"
python -m pytest tests/ -q -m "not live"
git diff --check
```

- **Full offline suite required:** yes
- **Live test:** no
