# Application JD version release verification

- Verification date: 2026-08-06
- Branch: `feat/20260805-application-jd-versions`
- Feature baseline: `455e081`
- Verification code HEAD: `f0df1ae`
- Status: implementation fixes verified; real-AI and browser release gates remain incomplete.

## Scope

This revision closes the consumer-path gaps for Application JD versions: Opportunity Fit v2 UI and Deep Review routing, current-version propagation for Mock Interview, read-only downstream JD displays, final JD CAS checks after Provider calls, frozen JD identity in Interview Preparation and Mock Interview snapshots, and machine-readable browser response metadata.

The legacy Opportunity Fit v1 POST write path is disabled. Historical v1 reads remain available. No new URL fetch, recruiting-site access, cross-domain write, or evidence-gate relaxation was added.

## Verification completed on this HEAD

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_mock_interview_api.py tests/test_jd_resume_ai_api.py tests/test_opportunity_fit_reviews_api.py -q` | 43 passed |
| Repository/API/JD-version targeted suites | 59 + 14 passed |
| `uv run pytest tests/test_application_jd_browser_harness.py -q` with recorded baseline and external allowlist | 6 passed |
| Frontend full suite: `npm.cmd test -- --run` | 104 files, 731 passed |
| Opportunity Fit rerender regression | 9 passed |
| `uv run ruff check src tests scripts/browser-network-audit.py` | passed |
| `uv run mypy src` | passed, 65 files |
| `npm.cmd exec tsc -- --noEmit` | passed |
| `npm.cmd run build` | passed, 3746 modules transformed |
| `git diff --check` | passed |

The browser harness scope check is fail-closed: it requires the recorded implementation baseline and an externally supplied ASCII allowlist. It checks tracked, staged, and untracked paths; the allowlist is not declared by the test module itself.

## Real-AI and browser gates

The following gates were not rerun for `f0df1ae` in this revision:

```powershell
uv run oc verify --profile real-ai --static-dir web/dist
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1 -Stage all
```

The prior isolated real-AI verification remains blocked by Provider `ReadTimeout`; browser acceptance remains fail-closed when `APPLICATION_JD_CDP_URL` is unavailable. API/local tests must not be reported as browser proof. No Provider secret, JD text, resume content, model output, or full request body is recorded here.

## Cleanup and remaining risk

- No push or merge was performed.
- The isolated browser/Provider process was not started in this revision.
- The recorded implementation baseline remains at `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` because release gates are incomplete.
- Remaining release blockers: full five-group backend gate on the final HEAD, real-AI verification, and browser-level CDP acceptance.
