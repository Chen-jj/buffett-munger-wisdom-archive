# TA-12 — Add injectable stdin text to the shared process runner

- **Status:** accepted
- **Module:** `infrastructure`
- **Decision coverage:** ADR-0005 section 7.1
- **Depends on:** TA-11
- **Depended on by:** TA-13

## Goal

Provide the smallest shared, injectable subprocess capability needed to send a
Codex translation envelope over stdin without shell interpolation or payload
logging.

## Exact scope

- Extend the existing shared `run_process()` adapter with an optional text stdin
  argument and pass it to the injected/subprocess runner through `input=`.
- Preserve argv-array execution, cwd, environment, timeout, captured text output,
  dry-run, missing-binary, timeout, and `check=True` behavior.
- Keep `ProcessResult` and normalized errors free of stdin content. A dry run
  must not echo or retain the supplied input.
- Add offline tests for exact runner arguments, Unicode input, absent input,
  dry-run non-execution, timeout, and existing-call compatibility.
- Update `src/infrastructure/AGENTS.md` only if its factual adapter contract
  needs clarification.

## Non-goals

- Do not add shell execution, streaming/Popen lifecycle management, JSON parsing,
  Codex-specific flags, auth detection, retries, or translation business logic.
- Do not change existing callers unless needed to preserve their behavior.

## Acceptance criteria

1. An injected runner receives the exact argv and stdin text without a shell.
2. Omitting stdin produces the current subprocess behavior and all existing
   infrastructure/media/transcription tests remain green.
3. Results, exceptions, and dry-run plans never contain the stdin payload.
4. Missing executables and timeouts retain their current normalized result
   semantics.
5. The complete offline suite passes.

## Verification

```bash
python -m pytest tests/infrastructure/test_infrastructure_adapters.py -q
python -m pytest tests/ -q -m "not live"
git diff --check
```

- **Full offline suite required:** yes
- **Live test:** no
