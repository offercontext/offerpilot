# Application JD version release verification

- Verification date: 2026-08-08
- Branch: `feat/20260805-application-jd-versions`
- Feature baseline: `455e081`
- Evidence execution HEAD: `c89639b`
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

The harness was tightened after that run. `browser-network-audit.py` now keeps a browser-level CDP heartbeat during the manual window, waits for `loadingFinished` before reading response bodies, writes an ASCII diagnostic with `failure_category`, target/session IDs, readiness, response counts, and close state, and fails closed on an unexpected disconnect or unavailable API response body. The PowerShell harness redirects auditor output, checks auditor/browser liveness before every stage, requires a successful `/api/chat/confirm` response (not only a request), verifies each of Triage, Material Kit, and Interview Preparation against the same frozen JD version, detects newly appearing database tables in snapshot comparisons, asserts per-stage cleanup and final database cleanup, retains the temporary directory if any child process does not exit, and waits for a normal auditor exit. These changes are covered by the 17 targeted tests above; a post-fix human browser run has not yet completed the confirmation and all three downstream stages.

## Cleanup and remaining risk

- No push or merge was performed.
- All gate subprocesses exited; no Provider proxy or browser process was retained. Isolated real-AI data directories were cleaned by the verifier.
- The recorded implementation baseline remains at `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` because release gates are incomplete.
- Remaining release blockers: Provider `ReadTimeout` in full real-AI verification and incomplete post-fix browser/CDP confirmation/consumer evidence. The browser harness no longer depends on a user-supplied `APPLICATION_JD_CDP_URL`; it must still complete the same-target Pilot confirmation and Triage -> Material Kit -> Interview Preparation sequence before release can be claimed.
