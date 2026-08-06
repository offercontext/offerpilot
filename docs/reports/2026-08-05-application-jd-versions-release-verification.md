# Application JD version release verification

- Verification date: 2026-08-06
- Branch: `feat/20260805-application-jd-versions`
- Feature baseline: `455e081`
- Verification code HEAD: `a4d92da`
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

The browser harness scope check is fail-closed: it requires the recorded implementation baseline and an externally supplied ASCII allowlist. It checks tracked, staged, and untracked paths; the allowlist is not declared by the test module itself.

## Real-AI and browser gates

The full real-AI gate was run twice against the final worktree content:

```powershell
uv run oc verify --profile real-ai --static-dir web/dist
```

Both runs failed with the external Provider `ReadTimeout`. The earlier smoke metadata mismatch was corrected by including the frozen JD version metadata in the expected fingerprint; the focused interview-preparation smoke then passed, so the remaining failure is the Provider timeout rather than a local fingerprint assertion. No retry or evidence-gate relaxation was added.

The browser harness was invoked as:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\application-jd-real-ai-browser-harness.ps1 -Stage all
```

It failed closed because `APPLICATION_JD_CDP_URL` was not configured; no browser-level acceptance evidence was claimed. A CDP endpoint is still required to prove the real UI flow and local-only browser network boundary. API/local tests must not be reported as browser proof. No Provider secret, JD text, resume content, model output, or full request body is recorded here.

## Cleanup and remaining risk

- No push or merge was performed.
- All gate subprocesses exited; no Provider proxy or browser process was retained. Isolated real-AI data directories were cleaned by the verifier.
- The recorded implementation baseline remains at `D:\Users\yuqi.chen\AppData\Local\Temp\offerpilot-application-jd-versions-baseline.txt` because release gates are incomplete.
- Remaining release blockers: Provider `ReadTimeout` in full real-AI verification and unavailable `APPLICATION_JD_CDP_URL` for browser-level CDP acceptance.
