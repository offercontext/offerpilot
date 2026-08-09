# Application JD version release verification

- Verification date: 2026-08-09
- Branch: `feat/20260805-application-jd-versions`
- Feature baseline: `455e081`
- Latest evidence execution HEAD: `0608466`
- Status: local and grouped release gates passed; real-AI and browser release gates remain blocked.

## Scope

This revision closes the consumer-path gaps for Application JD versions: Opportunity Fit v2 UI and Deep Review routing, current-version propagation for Mock Interview, read-only downstream JD displays, final JD CAS checks after Provider calls, frozen JD identity in Interview Preparation and Mock Interview snapshots, and machine-readable browser response metadata.

The legacy Opportunity Fit v1 POST write path is disabled. Historical v1 reads remain available. No new URL fetch, recruiting-site access, cross-domain write, or evidence-gate relaxation was added.

## Previously completed release gates

The grouped release gates below were completed before the later diagnostic-only changes. They remain the prior gate evidence; the current-HEAD checks are listed separately below.

| Command | Result |
| --- | --- |
| `windows-vitest-groups.ps1` (10 groups, fresh manifest) | 104 files, 778 passed; aggregate passed |
| `windows-pytest-groups.ps1` (agent/domain/knowledge/proposals/misc) | 1,808 collected; 1,804 passed, 4 allowed symlink-permission skips; aggregate passed |
| `uv run pytest tests/test_smoke.py -k interview_preparation` | 9 passed |
| `uv run ruff check .` | passed |
| `uv run mypy src` | passed, 65 files |
| `npm.cmd run build` (TypeScript plus Vite) | passed, 3747 modules transformed |
| `uv run oc smoke --static-dir web/dist` | passed |
| `uv run oc verify --profile local --static-dir web/dist` | passed |
| `git diff --check` | passed |
| `uv run pytest -q tests/test_application_jd_browser_harness.py tests/test_browser_network_audit.py` | 15 passed; one existing Starlette deprecation warning |

## Current-HEAD targeted verification

| Command | Result |
| --- | --- |
| `uv run pytest -q tests/test_interview_preparation_ai.py tests/test_interview_preparation_api.py` | 31 passed; existing framework deprecation warnings only |
| `uv run pytest -q tests/test_litellm_client.py tests/test_interview_preparation_controlled_diagnostic.py tests/test_full_real_ai_verify.py tests/test_interview_preparation_ai.py tests/test_interview_preparation_api.py` | 62 passed; existing framework deprecation warnings only |
| `uv run ruff check src/offerpilot/api.py tests/test_interview_preparation_api.py scripts/interview-preparation-controlled-provider-diagnostic.py src/offerpilot/ai/interview_preparation_proposals.py` | passed |
| `uv run mypy src` | passed, 65 files |
| PowerShell parser check for `scripts/application-jd-real-ai-browser-harness.ps1` | passed |
| `git diff --check` | passed |
| `uv run pytest -q tests/test_application_jd_browser_harness.py tests/test_browser_network_audit.py` | 17 passed; one existing Starlette deprecation warning |

The browser harness scope check is fail-closed: it requires the recorded implementation baseline and an externally supplied ASCII allowlist. It checks tracked, staged, and untracked paths; the allowlist is not declared by the test module itself.

## Isolated JD and real-AI gates

The isolated JD-only real-AI-profile smoke was rerun on `845f559`:

```powershell
uv run oc verify-application-jd --profile real-ai --static-dir web/dist
```

It passed in 15,763 ms with exit code 0. This command intentionally does not call a Provider: it verifies the synchronous JD version save, current-version CAS, metadata-only history, and cleanup while copying the real configuration silently. Therefore it is not evidence of a model response.

The full real-AI gate was previously run twice against the then-final worktree content, and was rerun on the current HEAD:

```powershell
uv run oc verify --profile real-ai --static-dir web/dist
```

The current-HEAD run failed at the first real interview-preparation Provider call with `ReadTimeout`. No Provider response was accepted, and no evidence contract, retry whitelist, or timeout was widened. The previous full-gate runs had the same external timeout category; this remains a release blocker.

To separate Provider transport behavior from the application contract, the controlled local Provider diagnostic was run after the timeout diagnosis:

```powershell
uv run ruff check scripts/interview-preparation-controlled-provider-diagnostic.py
uv run python scripts/interview-preparation-controlled-provider-diagnostic.py --static-dir web/dist
```

It exited 0 with `status=passed`, `provider_calls=3`, and elapsed time 4,102 ms. The controlled endpoint was an ephemeral loopback OpenAI-compatible server and the model was `controlled-interview-preparation`. The three HTTP responses were all 200; the local server observed request body sizes of 3,362, 3,358, and 3,363 bytes; redacted Provider request-id hashes were `e44e2eeada3d`, `2755f83a7e3e`, and `1c99ad93a902`. Safe diagnostics recorded three successful responses with no repair attempt, no failure category, durations of 1,285 ms, 32 ms, and 10 ms, and the same redacted request-id hashes. The frozen evidence catalog contained 3 snapshots, 3 JD entries, 9 resume facts, and 0 knowledge entries. No secret, JD text, resume content, or model output was written to the report. This proves the complete response path and strict local validation, but does not prove the external Provider is stable.

The full real-AI verification was then rerun once with the request metadata audit enabled. It exited 1 after 78,131 ms at the first interview-preparation Provider request with `ReadTimeout` through the configured proxy; no Provider response was accepted. No business retry was added.

### Full versus controlled Provider metadata

The comparison used the same `_run_real_ai_interview_preparation_smoke` path and the same current product code. The full run used the silently read existing configuration file `D:\Users\yuqi.chen\.offerpilot\config.json`: active provider `default`, type `openai_compatible`, model `deepseek-v4-flash`, endpoint `https://api.deepseek.com:443`, `supports_json_schema=false`, and no configured fallback. The controlled run silently copied that configuration shape into an isolated temporary directory, replacing only the active endpoint with an ephemeral loopback server and the model with `controlled-interview-preparation`.

| Redacted request metadata | Full real-AI | Controlled local | Comparison |
| --- | --- | --- | --- |
| Provider type | `openai_compatible` | `openai_compatible` | same |
| Model | `deepseek-v4-flash` | `controlled-interview-preparation` | intentionally different |
| Endpoint | `https://api.deepseek.com:443` | loopback `http://127.0.0.1:<ephemeral>` | intentionally different |
| Response mode | `text_json` | `text_json` | same |
| Explicit LiteLLM `max_tokens` / `max_completion_tokens` | `null` | `null` | same; diagnostic records explicit payload only |
| Explicit LiteLLM timeout | `null` | `null` | same; diagnostic records explicit payload only |
| App smoke HTTP timeout | `60.0s` | `60.0s` | same |
| First input fingerprint | `64ba822e...4d6f1e7c` | `64ba822e...4d6f1e7c` | exact match |
| First schema fingerprint | `12ae32cb...3d82e126` | `12ae32cb...3d82e126` | exact match |
| First message count / bytes | `2 / 3306` | `2 / 3306` | exact match |
| First serialized Provider-payload bytes | `3354` | `3369` | model/transport payload differs; input projection matches |

The controlled run completed three successful Provider calls in 4,102 ms with no repair and no failure category. Its metadata serialized Provider-payload sizes were 3,369, 3,365, and 3,370 bytes; the local server observed 3,362, 3,358, and 3,363 bytes on the wire. The audit field is explicitly scoped to the serialized Provider payload without authentication or endpoint fields; it is not a TLS wire capture. The full run emitted one request metadata record before the remote timeout. Its first input and schema fingerprints, message count/bytes, response mode, explicit token settings, and explicit timeout setting exactly matched the controlled first request. The diagnostic intentionally does not claim to observe effective LiteLLM/proxy defaults when the explicit fields are null. Therefore the captured difference is the configured remote Provider/model route, not a prompt, schema, frozen JD/Resume, or explicit client timeout mismatch. This identifies the remaining blocker as external Provider/transport behavior; it does not justify changing evidence validation or adding business retries.

The tool-only diagnostic and harness changes in `7d3bb82`, `078b8e4`, `8a59407`, `ededffb`, `acd219a`, `b1908f8`, and `2b14677` do not alter the interview-preparation API or evidence contract. The request metadata audit is diagnostic-only and fail-open: a local audit-file or serialization error cannot prevent the Provider call. It records hashes, tuple metadata, counts, scoped serialized-payload bytes, mode, and explicit runtime parameters; it does not record prompts, snapshots, model output, API keys, or full URLs.

The browser harness was invoked as:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1 -Stage all
```

The harness now self-starts a temporary headless Chrome/CDP endpoint when `APPLICATION_JD_CDP_URL` is absent. The endpoint started successfully and the dedicated browser target reached the page. The real browser run completed the UI JD saves and history action, then triggered the Pilot JD input submission; the page-target CDP session closed while waiting for the Pilot confirmation response. Consequently the Pilot network response, Stage A confirmation, and all three consumer stages were not proven; no browser-level success is claimed. This is an incomplete browser/CDP acceptance result, not a reason to relax the Provider or JD contracts.

No Provider secret, JD text, resume content, model output, or full request body is recorded here.

### Latest Pilot stream boundary (2026-08-08)

After the lease/replay boundary tests passed, one final isolated `Stage all` attempt was made and then stopped. The attempt used a temporary data directory and the existing DeepSeek configuration; no further real-Provider retry was performed.

The persisted browser audit proves the following boundary:

- UI JD save: one `POST /api/applications/1/job-description/versions` returned `201`, with `source_kind=ui` and `jd_version_id=1`.
- UI JD read-back returned `200` for version 1.
- No Pilot JD-version POST or `source_kind=pilot` response was recorded.
- No `POST /api/chat/confirm` or `/api/chat/confirm/stream` request was recorded, so the confirmation token was not consumed through the confirmation endpoint and Pilot JD v2 was not written in this attempt.
- No duplicate JD-version POST or duplicate Pilot submission was observed.
- Pilot generation failed before a confirmation card with `MidStreamFallbackError` / incomplete chunked read. Triage, Material Kit, and Interview Preparation therefore did not run.

The temporary application data was removed by the harness; the token-row state cannot be queried after cleanup. The network audit is therefore the retained fail-closed evidence for the unconsumed-token/no-v2-write classification:

- Browser audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-browser-audit-20260808223208.jsonl`
- Provider egress audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-provider-egress-20260808223208.jsonl`

The controlled lease/fencing tests were rerun with `4 passed`, covering live-lease same-key replay, expired-lease takeover, provider-error heartbeat cleanup, and two-connection single-owner behavior. No lease, CAS, idempotency, evidence-contract, or JD-version code change was made for this boundary.

The release remains blocked. The only next release condition is a successful DeepSeek Pilot response that produces the confirmation card, followed by one complete `Stage all`; historical 409 investigation and unbounded retries remain out of scope.

### Isolated Ark Provider attempt (2026-08-08)

At the user's request, the harness was run once with an isolated Provider override using the Ark endpoint and `doubao-seed-2.1-turbo`. The formal OfferPilot configuration was not changed, and the API key was read only from a local secret file; it was not written to source, reports, or audit output.

- UI JD v1 save returned `201`.
- The Pilot `/api/chat/stream` request reached `ark.cn-beijing.volces.com:443` and the application received `litellm.NotFoundError` / HTTP `404` before a confirmation card was produced.
- No Pilot confirmation request was sent, no token was consumed, and no Pilot JD v2 was written.
- No duplicate JD-version or Pilot submission was observed.
- The harness stopped at Stage A and cleaned the service, browser, temporary data, and ports. Triage, Material Kit, Interview Preparation, and complete `Stage all` remain unproven.

Retained diagnostics:

- Browser audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-browser-audit-20260808231829.jsonl`
- Provider egress audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-provider-egress-20260808231829.jsonl`

This result is an Ark endpoint/model compatibility failure, not evidence of a JD-version, token-consistency, CAS, lease, or evidence-contract defect. No further Provider retry was made.

### Corrected Ark `/v1` endpoint attempt (2026-08-08)

The Ark base URL was corrected to include `/api/coding/v1`; the client then appended the chat-completions route. A single isolated `Stage all` run was continued with this configuration and the formal configuration remained unchanged.

- Pilot generated a non-empty JD proposal and a real confirmation card.
- One confirmation click produced `POST /api/chat/confirm/stream` with `200`.
- JD history list/detail reads returned `200`; version 2 was read back with `source_kind=pilot`.
- Triage then returned `provider_unknown` after 91,576 ms with `failure_category=provider_http_5xx`; the frozen JD, resume, and user-assertion evidence counts were each 1.
- The harness preserved the original key and attempted its single exact replay. The replay returned `409` before another Provider request and failed the same-input replay guard because no replay Provider fingerprint was produced. This is the previously known historical 409 boundary; it is not being retried or investigated further.
- Material Kit and Interview Preparation did not run. The harness cleaned the service, browser, temporary data, and ports.

Retained diagnostics:

- Stage diagnostics: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\stage-all-20260808-233439898-75f3322024f64c14b94fcd022264041b.jsonl`
- Browser audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-browser-audit-20260808234417.jsonl`
- Provider egress audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-provider-egress-20260808234417.jsonl`

This run proves that the corrected Ark endpoint can complete Pilot JD proposal/confirmation and create the Pilot JD version, but it does not satisfy complete `Stage all` release evidence.

The harness was tightened after that run. `browser-network-audit.py` now keeps a browser-level CDP heartbeat during the manual window, waits for `loadingFinished` before reading response bodies, writes an ASCII diagnostic with `failure_category`, target/session IDs, readiness, response counts, and close state, and fails closed on an unexpected disconnect or unavailable API response body. The PowerShell harness redirects auditor output, checks auditor/browser liveness before every stage, requires a successful `/api/chat/confirm` response (not only a request), verifies each of Triage, Material Kit, and Interview Preparation against the same frozen JD version, detects newly appearing database tables in snapshot comparisons, asserts per-stage cleanup and final database cleanup, retains the temporary directory if any child process does not exit, and waits for a normal auditor exit. These changes are covered by the 17 targeted tests above; a post-fix human browser run has not yet completed the confirmation and all three downstream stages.

### Final DeepSeek Stage all attempt (2026-08-09)

One final isolated real-Provider `Stage all` attempt was made from HEAD `bac4194` with the formal DeepSeek configuration (`deepseek-v4-flash`, endpoint host `api.deepseek.com:443`). The key was read from the local configuration only and is not recorded here.

- The browser request failed before a valid HTTP response was received while waiting for the Pilot streaming response.
- No confirmation card was produced, no confirmation token was consumed, and no Pilot JD v2 or downstream Triage/Material Kit/Interview Preparation write was accepted.
- No concrete HTTP 500 or Provider response status was obtained; this is retained as a transport-level failure, not attributed to JD version logic, CAS, lease, or evidence validation.
- The unique real-Provider acceptance allowance is exhausted. No further retry, business-code change, contract relaxation, or Provider retry was performed.

Retained diagnostic:

- Browser audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-browser-audit-20260809144402.jsonl`

The temporary service, browser, Provider proxy, and isolated data were cleaned. The branch remains paused and must not be merged or pushed. Recovery requires either new external DeepSeek stability evidence with explicit authorization for one new acceptance attempt, or an explicitly approved change to another formal Provider configuration.

### Isolated Ark formal-configuration acceptance (2026-08-09)

At the user's request, one valid isolated browser acceptance was run with an Ark override. The formal configuration was not changed; the isolated configuration used base URL `https://ark.cn-beijing.volces.com/api/coding/v1` and model `doubao-seed-2.1-turbo`. The API key was read from a local secret file and is not recorded here.

- Stage A completed: UI JD v1 was saved, Pilot generated and confirmed a JD proposal, and JD v2 was read back as `source_kind=pilot`. Version history and v2 detail were also read successfully.
- Triage used `jd_version_id=2`, resume evidence count 1, JD evidence count 1, and two user assertions. The Provider egress audit connected only to `ark.cn-beijing.volces.com:443`.
- Ark returned HTTP 500 after 91,465 ms. The local API safely mapped it to `502 opportunity_fit_provider_error` and recorded `provider_http_5xx`; the Triage Provider call count was 1.
- The harness performed its single same-key replay. The replay returned HTTP 409 before another Provider call (`provider_request_count=0`); the replay guard verified the frozen input but did not produce a replay Provider fingerprint. Material Kit, Interview Preparation, and complete `Stage all` therefore remain unproven.

Retained diagnostics:

- Stage diagnostics: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\stage-all-20260809-151006076-981de1fa82a74e48b46c96454957e576.jsonl`
- Browser audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-browser-audit-20260809151916.jsonl`
- Provider egress audit: `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-stage-diagnostics\failed-provider-egress-20260809151916.jsonl`

This is an external Ark Triage stability failure, not evidence of a JD-version, CAS, lease, or evidence-contract defect. The isolated service, browser, Provider proxy, and data directory were cleaned. No further Ark retry was made; the branch remains blocked and must not be merged or pushed.

### Controlled local Triage boundary diagnostic (2026-08-09)

To distinguish a shared local 90-second boundary from an external Provider or network boundary, one isolated API-only Triage run used a loopback OpenAI-compatible Provider. The local server delayed its valid, strict `safe_empty` Triage response by exactly 100 seconds; no Ark or DeepSeek request was made.

- The first Triage request returned `201 ready` after `100,996 ms`.
- The controlled Provider received exactly one request and completed it after `100,000 ms`; the Provider result audit was `success`, with no failure category. The only egress host was `127.0.0.1`.
- The redacted Provider input fingerprint was `9b0201da...27edb5` (full hash retained only in the temporary diagnostic); the canonical request-payload fingerprint was `7fad211c...7fd90aa7`.
- An exact same-key replay returned `200 ready` in `7 ms` and the Provider call count remained `1`.
- A deliberately changed same-key payload returned `409` in `6 ms` with the precise `error_code=opportunity_fit_idempotency_conflict`; its canonical payload fingerprint differed (`25a137ca...346580b`). It made no Provider call.

This controlled result does not reproduce a local 90-second timeout: the local OfferPilot/LiteLLM path accepted a valid response beyond 100 seconds. The exact same-input replay also did not reproduce the historical 409; the captured 409 is the deterministic source/idempotency-conflict path. Therefore the historical Ark/DeepSeek failures near 91–92 seconds remain attributable to an external Provider, VPN/proxy, or upstream gateway boundary until new evidence distinguishes those layers. No timeout, retry, lease, CAS, or evidence contract was changed. The temporary controlled service, database, and audit files were cleaned.

### No-cost network boundary probes (2026-08-09)

No model request was made. The machine's active proxy environment was `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY=http://127.0.0.1:7897`; no `NO_PROXY` override was set.

- An unauthenticated `GET /v1/models` to `api.deepseek.com` returned `401` after `0.446 s` total, with TLS application-connect time `0.290 s`.
- An unauthenticated `GET /api/coding/v1/models` to `ark.cn-beijing.volces.com` returned `401` after `0.325 s`, with TLS application-connect time `0.287 s`.
- Generic delayed-response probes did not provide a usable long-read sample: `httpbin.org/drip` returned `503` in `2.851 s`, and `httpstat.us?sleep=100000` closed the connection in `3.458 s`. These endpoints were rejected before the intended delay, so they are not evidence of a 90-second cutoff.

The probes confirm basic DNS/TCP/TLS/provider-host reachability but do not yet identify which layer closes a 91–92 second model response. Product code remains unchanged. After the VPN/proxy/gateway boundary is adjusted or otherwise explained, only one real `Stage all` run should be authorized.

## Cleanup and remaining risk

- No push or merge was performed.
- All gate subprocesses exited; no Provider proxy or browser process was retained. Isolated real-AI data directories were cleaned by the verifier.
- The recorded implementation baseline remains at `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` because release gates are incomplete.
- Remaining release blockers: DeepSeek Pilot transport instability and Ark Triage HTTP 500 with an unproven downstream `Stage all`. The branch is paused; do not claim release readiness until a formally approved Provider produces a complete successful browser acceptance.
