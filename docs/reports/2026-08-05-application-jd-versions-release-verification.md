# Application JD version release verification

- Verification date: 2026-08-06
- Branch: `feat/20260805-application-jd-versions`
- Feature baseline: `455e081`
- Evidence execution HEAD: `271d46e` (report-only commits follow)
- Status: local and grouped release gates passed; real-AI and browser release gates remain blocked.

## Scope

This revision closes the consumer-path gaps for Application JD versions: Opportunity Fit v2 UI and Deep Review routing, current-version propagation for Mock Interview, read-only downstream JD displays, final JD CAS checks after Provider calls, frozen JD identity in Interview Preparation and Mock Interview snapshots, and machine-readable browser response metadata.

The legacy Opportunity Fit v1 POST write path is disabled. Historical v1 reads remain available. No new URL fetch, recruiting-site access, cross-domain write, or evidence-gate relaxation was added.

## Verification completed on this HEAD

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

It exited 0 with `status=passed`, `provider_calls=3`, and elapsed time 4,904 ms. The controlled endpoint was an ephemeral loopback OpenAI-compatible server and the model was `controlled-interview-preparation`. The three HTTP responses were all 200; request body sizes were 2,116, 2,112, and 2,117 bytes; redacted Provider request-id hashes were `e44e2eeada3d`, `2755f83a7e3e`, and `1c99ad93a902`. No secret, JD text, resume content, or model output was written to the report. This proves the complete response path and strict local validation, but does not prove the external Provider is stable.

The full real-AI verification was then rerun against the same product behavior. It exited 1 after 80,141 ms at the first interview-preparation Provider request with `ReadTimeout` through the configured proxy; no Provider response was accepted. The tool-only diagnostic and harness changes in `7d3bb82`, `078b8e4`, `8a59407`, and `271d46e` do not alter the interview-preparation API or evidence contract, so this remains an external Provider/transport blocker rather than a reason to change product semantics.

The browser harness was invoked as:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1 -Stage all
```

The harness now self-starts a temporary headless Chrome/CDP endpoint when `APPLICATION_JD_CDP_URL` is absent. The endpoint started successfully and the dedicated browser target reached the page. The real browser run completed the UI JD saves and history action, then triggered the Pilot JD input submission; the page-target CDP session closed while waiting for the Pilot confirmation response. Consequently the Pilot network response, Stage A confirmation, and all three consumer stages were not proven; no browser-level success is claimed. This is an incomplete browser/CDP acceptance result, not a reason to relax the Provider or JD contracts.

No Provider secret, JD text, resume content, model output, or full request body is recorded here.

The harness was tightened after that run. `browser-network-audit.py` now keeps a browser-level CDP heartbeat during the manual window, waits for `loadingFinished` before reading response bodies, writes an ASCII diagnostic with `failure_category`, target/session IDs, readiness, response counts, and close state, and fails closed on an unexpected disconnect or unavailable API response body. The PowerShell harness redirects auditor output, checks auditor/browser liveness before every stage, requires a successful `/api/chat/confirm` response (not only a request), verifies each of Triage, Material Kit, and Interview Preparation against the same frozen JD version, asserts per-stage cleanup and final database cleanup, and waits for a normal auditor exit. These changes are covered by the 15 targeted tests above; a post-fix human browser run has not yet completed the confirmation and all three downstream stages.

## Cleanup and remaining risk

- No push or merge was performed.
- All gate subprocesses exited; no Provider proxy or browser process was retained. Isolated real-AI data directories were cleaned by the verifier.
- The recorded implementation baseline remains at `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` because release gates are incomplete.
- Remaining release blockers: Provider `ReadTimeout` in full real-AI verification and incomplete post-fix browser/CDP confirmation/consumer evidence. The browser harness no longer depends on a user-supplied `APPLICATION_JD_CDP_URL`; it must still complete the same-target Pilot confirmation and Triage → Material Kit → Interview Preparation sequence before release can be claimed.
