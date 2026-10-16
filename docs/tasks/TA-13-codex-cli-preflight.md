# TA-13 — Implement Codex CLI and ChatGPT-auth preflight

- **Status:** accepted
- **Module:** `translation/infrastructure`
- **Decision coverage:** ADR-0005 sections 4.1, 5–6, and 8 preflight errors
- **Depends on:** TA-12
- **Depended on by:** TA-14

## Goal

Fail closed before translation when the configured executable, CLI capability,
or authentication cannot prove that the request will use ChatGPT entitlement
rather than usage-based API billing.

## Exact scope

- Add the Codex CLI provider/preflight infrastructure boundary using an injected
  process runner so all tests are offline.
- Accept only a plain executable path/name, never a shell fragment or arbitrary
  wrapper command. Resolve and verify the actual Codex CLI through its supported
  version/capability output.
- Obtain the actual `codex --version` value for the immutable provider identity
  and verify that the required `exec` flags are supported.
- Before the first translation call, run `codex login status` once per provider
  instance. Recognized ChatGPT login passes; not logged in, API-key login,
  unrecognized login output, or a failed forced-login check fails closed.
- Define the fixed identity: provider `codex-cli-chatgpt`, model `gpt-5.6-sol`,
  protocol `translation.codex-cli.v1`, actual CLI version, ChatGPT auth, exec
  mode, high effort, read-only sandbox, ephemeral session, and structured output.
- Map missing/unsupported CLI to permanent `configuration`, non-ChatGPT auth to
  permanent `authentication`, and detected API billing to permanent
  `api_billing_not_allowed`. Error text and metadata must not contain auth-file
  contents, tokens, prompts, source text, translations, or uncontrolled stderr.
- Add exhaustive fake-runner tests, including proof that no preflight command
  modifies global login state or launches a browser.

## Non-goals

- Do not call `codex login`, read `~/.codex/auth.json`, invoke the model, parse a
  translation response, implement retries, or fall back to OpenAI.
- Do not infer model entitlement from a model list; TA-16 proves it by a real
  call.

## Acceptance criteria

1. Version, required CLI capabilities, and ChatGPT login are mechanically
   verified before any translation execution.
2. Preflight runs at most once in a workflow/provider instance and its actual
   CLI version appears in the full provider identity.
3. Every ambiguous or non-ChatGPT auth state fails permanently and cannot reach
   translation execution.
4. Fake-runner tests cover every safety/error branch without touching the real
   CLI, network, browser, credential store, or OpenAI API.
5. The complete offline suite passes.

## Verification

```bash
python -m pytest tests/translation/ -q -m "not live" -k "codex and preflight"
python -m pytest tests/ -q -m "not live"
git diff --check
```

- **Full offline suite required:** yes
- **Live test:** no
