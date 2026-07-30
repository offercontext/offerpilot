# Release validation report: evidence-gated interview preparation

Date: 2026-07-30
Branch: `feat/20260724-evidence-gated-interview-preparation`
Validation HEAD: `056d9d6`
Status: not pushed, not merged

## Narrow fix in this validation round

- Normal `strengths`, `practice_points`, and `next_practice_steps` items now require at least one completed-turn evidence reference with `source="turn"`.
- JD and Resume references remain supplementary and cannot replace Turn evidence.
- Missing Turn evidence is eligible for at most one constraint-completion repair. Unknown paths, excerpt mismatches, forged references, and limits remain terminal contract failures.
- Evidence references are validated before the Turn-evidence repair category is considered; invalid source, path, or excerpt failures therefore cannot trigger a repair call.
- Repair uses the same frozen input and does not include the prior model response. Two failed validations remain `502 mock_interview_unverifiable`; no Proposal is written.

## Verification after the fix

- `uv run pytest tests/test_mock_interview_ai.py -q`: exit 0, 29 passed.
- All Mock Interview test files (`tests/test_mock_interview*.py`): exit 0, 106 passed.
- `uv run ruff check src/offerpilot/ai/mock_interview.py tests/test_mock_interview_ai.py`: exit 0.
- `uv run mypy src/offerpilot/ai/mock_interview.py`: exit 0.
- `uv run oc verify --profile real-ai --static-dir web/dist`: exit 0.
  - Interview feedback completed after two turns.
  - Other real-AI flows also completed, including Opportunity Fit, material proposal, interview preparation, interview review, and knowledge capture.
  - Mock Interview bounded attempts ended with `attempt_1:feedback:mock_interview_unverifiable:excerpt_mismatch`, `attempt_2:question_2:mock_interview_unverifiable:excerpt_mismatch`, then `attempt_3:success`; terminal failures were preserved and the successful retry used a new Attempt.
- `uv run oc verify-mock-interview --static-dir web/dist`: exit 0, `attempt_1:success`.

The earlier full release gate at `399462c` also passed: backend groups covered 1630 collected node IDs with no duplicates and only the four defined Windows symlink-capability skips; Ruff, Mypy, 203 frontend suites / 657 tests, TypeScript, production build, local smoke, and isolated local verify all exited 0. The current fix changes only the Mock Interview AI module and its tests; the focused post-fix gates above were rerun.

## Browser evidence

- The previously completed local read-only browser walk-through remains valid: dashboard suggestion, snooze/ignore session behavior, detail navigation, no write calls, and no console errors.
- A fresh isolated browser/CDP run reached the real two-turn feedback stage and produced a feedback Proposal with Turn evidence. The subsequent confirmation response was classified by the UI as `result_unknown`, so the final confirmation-and-history portion did not complete in that run. The system retained the original confirmation attempt as designed.
- Therefore this report does not claim a fresh isolated browser confirmation/history closure. API-level real-AI verification passed; it is not a substitute for that browser evidence.

## Cleanup and remaining risk

- Temporary isolated data, services, provider proxy, standalone browser, and CDP auditor were stopped and removed.
- No secret, Resume/JD content, or model output was recorded in this report.
- No push or merge was performed.
- Remaining release risk: repeat the isolated browser run until the confirmation and read-only history steps complete; retain any Provider/result-unknown outcome as evidence rather than bypassing the gate.
