# Interview Preparation Lease Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each step uses checkbox syntax and must be completed in order.

**Goal:** Keep a slow interview-preparation Provider call owned by one Attempt long enough to finish, while using the existing generation revision and provider call token to fence late results and preserve every existing evidence and error contract.

**Architecture:** Add an interview-preparation-only heartbeat around the existing Provider call in InterviewPreparationProposalsRepository. The heartbeat renews only provider_lease_until through short-lived database sessions; the final write uses status, generation revision, provider call token, and source_fingerprint as the fencing CAS. Confirmed ownership loss blocks the old result; an uncertain heartbeat outcome still reaches the final CAS so the database, not a local assumption, decides ownership.

**Tech Stack:** Python, SQLAlchemy, SQLite, pytest, FastAPI TestClient, existing ChatModel fakes and Provider barriers.

---

## 0. Execution boundary and file map

Implementation starts from feature baseline 6c712eb in D:\Users\yuqi.chen\offerpilot\.worktrees\feat-20260801-offer-negotiation. Before changing files, verify the branch, clean status, and baseline. Do not touch the repository root or its existing uncommitted work.

The implementation is limited to these files:

- Modify: src/offerpilot/repositories/interview_preparation_proposals.py
  - Add interview-preparation-only timing seams and the private heartbeat owner.
  - Keep the existing repository/API method names and request behavior.
  - Change only lease renewal, owner lifecycle, and final CAS conditions.
- Modify: tests/test_interview_preparation_repository.py
  - Add deterministic slow-provider, heartbeat, uncertain-renewal, fencing, takeover, and cleanup regressions.
- Modify: tests/test_interview_preparation_api.py
  - Add API-level pending/ready and same-key behavior checks where repository results are mapped to HTTP responses.
- Modify: tests/test_smoke.py
  - Add only the local smoke regression needed to prove a pending response can complete with the same request; do not alter smoke product scope.
- Do not modify: src/offerpilot/models.py, src/offerpilot/db.py, API route definitions, frontend files, Offer files, or AI schema/validation files. No migration is required.
- Do not create a generic lease framework or extend this behavior to another Proposal repository.

No step may add a new HTTP field, database field, state, business retry, Provider call, or evidence exception.

## Task 1: Add deterministic timing and ownership test seams

**Files:**
- Modify: tests/test_interview_preparation_repository.py
- Modify: src/offerpilot/repositories/interview_preparation_proposals.py

- [ ] Step 1: Add a failing constructor/timing regression.

Create repository instances with short injected values, for example:

~~~python
repository = InterviewPreparationProposalsRepository(
    factory,
    lease_seconds=0.05,
    heartbeat_interval_seconds=0.01,
)
~~~

Assert that the existing 30-second defaults remain the production defaults and that the test instance exposes the short lease values used by the heartbeat. Run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q
~~~

Expected result before implementation: the new constructor arguments are rejected or the lease remains fixed at the module constant.

- [ ] Step 2: Implement only the minimum timing seams.

Add an interview-preparation-only heartbeat interval constant of 10 seconds. Keep LEASE_SECONDS at 30. Make lease duration and heartbeat interval keyword-only constructor options with production defaults. Route all lease deadline calculations in this repository through the repository’s injected values. Keep the existing session factory and model call signatures unchanged.

Define the private owner object as _InterviewPreparationLeaseHeartbeat with start(), stop_and_join(), heartbeat_count, confirmed_ownership_lost, and heartbeat_uncertain. Its renew_once() operation must be independently callable by tests and must use the same conditional update as the background loop. The repository constructor may accept a waiter callable defaulting to stop_event.wait; no waiter or timing option may be exposed through the HTTP API.

Use an injectable waiting seam or an Event.wait-compatible callable so tests can stop the worker deterministically. The production default must remain a stoppable Event waiter and must not hold a database session while waiting.

- [ ] Step 3: Run the seam test and current repository suite.

Run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q
~~~

Expected result: the new timing/default tests pass and all pre-existing repository tests remain green.

- [ ] Step 4: Commit the seam separately.

~~~powershell
git add tests/test_interview_preparation_repository.py src/offerpilot/repositories/interview_preparation_proposals.py
git commit -m "test: AI add interview preparation lease timing seams"
~~~

## Task 2: Implement and verify the normal heartbeat path

**Files:**
- Modify: tests/test_interview_preparation_repository.py
- Modify: src/offerpilot/repositories/interview_preparation_proposals.py

- [ ] Step 1: Add the failing slow-provider test.

Use the existing BlockingSafeEmptyModel and its entered/release barriers. Configure a short lease and heartbeat interval, hold the Provider beyond the injected lease, and assert:

~~~python
assert result.created is True
assert result.pending is False
assert result.attempt_status == "ready"
assert model.calls == 1
~~~

Read the row afterward and assert attempt_status is ready, proposal_json is populated, provider_call_token is empty, and provider_lease_until is None.

Run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q -k "slow or heartbeat"
~~~

Expected result before implementation: the old owner returns a pending result after its short lease expires.

- [ ] Step 2: Add the same-key concurrency regression.

While the first model is blocked, call the same key through a second repository backed by a second SQLite connection. Assert the second result is pending/generating, its call path does not invoke a second Provider call, and the first result later becomes ready.

The test must distinguish Provider calls from heartbeat updates. The model call counter must remain exactly 1.

- [ ] Step 3: Implement the private owner-scoped heartbeat.

After create_generated or an expired-lease takeover commits its row, construct _InterviewPreparationLeaseHeartbeat carrying only Attempt ID, owner revision, owner token, lease duration, interval, session factory, stop signal, and the two local status flags.

Each tick must:

1. Open a fresh session.
2. Start a short transaction.
3. Update only provider_lease_until to current time plus the configured lease duration.
4. Require Attempt ID, attempt_status generating, matching generation_revision, and matching provider_call_token.
5. Commit and close the session before sleeping again.
6. Set confirmed_ownership_lost only when rowcount is 0 or an explicit read proves status/revision/token mismatch.
7. Set heartbeat_uncertain for lock/session/connection exceptions or an abnormal worker exit when no mismatch is proven.
8. Stop without Provider or network work when the owner sets the stop signal.

Do not share a SQLAlchemy Session or connection with the Provider call or another heartbeat tick.

- [ ] Step 4: Wrap the existing Provider and validation call in the heartbeat lifecycle.

Start the worker immediately before generate_interview_preparation_proposal. Stop it in the common cleanup path after the Provider/validation call returns or raises. Wait for the worker to finish and close its session. Do not change Provider input, response format, repair count, validation, or diagnostics.

- [ ] Step 5: Run the slow-provider and concurrency tests.

Run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q -k "slow or heartbeat or same_key"
~~~

Expected result: all selected tests pass; the Provider model counter is exactly 1 for the slow successful Attempt.

The same run must include a preflight lifecycle assertion: preflight may return an existing ready/pending row or indicate that an expired row needs provider resolution, but it must never start a heartbeat. Only the subsequent create_generated owner starts one heartbeat, and an unconfigured Provider path leaves no worker or session behind.

- [ ] Step 6: Commit the normal heartbeat slice.

~~~powershell
git add tests/test_interview_preparation_repository.py src/offerpilot/repositories/interview_preparation_proposals.py
git commit -m "feat: AI keep interview preparation lease alive"
~~~

## Task 3: Change final persistence to fencing-only CAS

**Files:**
- Modify: tests/test_interview_preparation_repository.py
- Modify: src/offerpilot/repositories/interview_preparation_proposals.py

- [ ] Step 1: Add a failing expired-lease final-write regression.

Create an Attempt with matching status, revision, token, and source fingerprint, then make provider_lease_until expire before the final persistence transaction while no takeover occurs. Release a successful Provider result and assert the result is still ready. This must fail against the current lease-expiry check.

- [ ] Step 2: Add confirmed versus uncertain heartbeat tests.

Cover both cases:

- A heartbeat update returns zero rows after the row’s token/revision is changed. Assert confirmed_ownership_lost, no old result write, and the current row remains authoritative.
- A heartbeat update raises a transient SQLite lock error and no other owner changes the row. Assert heartbeat_uncertain, then assert the final fencing CAS writes the valid Provider result as ready.

The second case is required to prove that “could not confirm renewal” does not become “confirmed lost ownership.”

- [ ] Step 3: Implement the final CAS change.

After heartbeat cleanup, reject the old result early only when confirmed_ownership_lost is set. For heartbeat_uncertain, continue to the existing final transaction. Rebuild the current source snapshot and compare its fingerprint before writing.

The final conditional update/write must require:

~~~text
attempt_status == generating
generation_revision == owner_revision
provider_call_token == owner_token
current_source_fingerprint == frozen_source_fingerprint
~~~

It must not require provider_lease_until to be later than the current time. A successful write clears provider_call_token and provider_lease_until and transitions to ready. A failed CAS reads the current row and returns the existing safe state; it never fabricates a 201 ready and never modifies the new owner.

- [ ] Step 4: Run final-CAS tests and existing repository tests.

Run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q -k "lease or fencing or ownership or source"
~~~

Then run:

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py -q
~~~

Expected result: the expired-lease/no-takeover case is ready, the confirmed-loss case cannot write, the uncertain-renewal case can write, and all existing tests pass.

- [ ] Step 5: Commit the fencing slice.

~~~powershell
git add tests/test_interview_preparation_repository.py src/offerpilot/repositories/interview_preparation_proposals.py
git commit -m "fix: AI fence late interview preparation results"
~~~

## Task 4: Add takeover and late-result concurrency coverage

**Files:**
- Modify: tests/test_interview_preparation_repository.py
- Modify: tests/test_interview_preparation_api.py
- No production file is expected in this task; the heartbeat and fencing implementation is completed in Tasks 2 and 3.

- [ ] Step 1: Add the dual-connection takeover test.

Use two independent session factories connected to the same SQLite database. Stop the first heartbeat, force its lease to expire, and start two same-key calls concurrently. Assert exactly one transaction changes generation_revision and provider_call_token, exactly one new owner invokes the Provider, and the other caller returns the current pending/ready state without a second owner.

- [ ] Step 2: Add the late-old-provider regression.

Hold the old owner’s Provider result behind a barrier. Let a new owner safely take over and write a different valid result. Release the old Provider and assert the old result cannot change proposal_json, proposal_hash, attempt_status, generation_revision, or the cleared token/lease of the new ready row.

- [ ] Step 3: Add the stop-to-CAS race regression.

Stop the old heartbeat, then make a new owner take over immediately before the old owner’s final transaction. Assert the old result does not return a false ready result and the database contains only the new owner’s result.

- [ ] Step 4: Add API replay assertions.

In tests/test_interview_preparation_api.py, verify that a same-key request during a live lease remains 202 with the existing pending fields, that a completed slow request returns the existing 200/201 ready shape, and that a provider_unknown response retains the original key and remains replayable without a heartbeat-created extra Provider call.

Do not introduce a new endpoint or response field.

- [ ] Step 5: Run the concurrency/API group.

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py -q
~~~

Expected result: the full selected group passes, with exactly one successful takeover and no late-result overwrite.

- [ ] Step 6: Commit the takeover slice.

~~~powershell
git add tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py src/offerpilot/repositories/interview_preparation_proposals.py
git commit -m "test: AI cover interview preparation takeover fencing"
~~~

## Task 5: Preserve failure semantics and prove cleanup

**Files:**
- Modify: tests/test_interview_preparation_repository.py
- Modify: tests/test_interview_preparation_api.py
- Modify: tests/test_smoke.py
- No production file is expected in this task; failure behavior must be preserved by the implementation already completed in Tasks 2 and 3.

- [ ] Step 1: Add failure-path cleanup assertions.

Use existing FailingModel, EventDeletingModel, safe-empty and format-failure fixtures. For Provider exception, source deletion, source drift, strict contract failure, one permitted format repair, and safe_empty, assert the original status/error semantics and exactly one heartbeat worker per owner. After each call, assert no heartbeat worker remains active and every heartbeat session was closed.

- [ ] Step 2: Add abnormal heartbeat and lock uncertainty cleanup tests.

Force a heartbeat session error and an abnormal worker exit without changing the row. Assert the local state is heartbeat_uncertain, the Provider result still reaches final fencing CAS, and the worker/session cleanup is complete. Separately change the row’s token/revision and assert confirmed_ownership_lost prevents old result persistence.

- [ ] Step 3: Keep the smoke polling contract unchanged and cover same-request completion.

In test_real_ai_interview_preparation_smoke_retries_pending_results_with_same_request, explicitly assert that the request payload recorded for the pending response is byte-for-byte equivalent to the next request payload, including the same idempotency_key, event_id, resume_id, JD, Knowledge selections, and user assertions. The smoke helper must continue to accept 202 only as a bounded pending state and then require 200/201 terminal success. It must not add business retries or relax evidence validation.

- [ ] Step 4: Run failure and smoke tests.

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py tests/test_smoke.py -q
~~~

Expected result: all existing failure semantics pass, no secret/model output appears in error responses or captured diagnostics, and all selected tests pass.

- [ ] Step 5: Commit the failure/cleanup slice.

~~~powershell
git add tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py tests/test_smoke.py src/offerpilot/repositories/interview_preparation_proposals.py
git commit -m "test: AI preserve interview preparation failure cleanup"
~~~

## Task 6: Review the implementation boundary and run static checks

**Files:**
- No new product files.
- Review the complete diff from feature baseline 6c712eb.

- [ ] Step 1: Verify the changed-file boundary.

Run from the worktree root:

~~~powershell
$changed = git diff --name-only 6c712eb..HEAD
$changed
if ($changed | Where-Object { $_ -match '^(src/offerpilot/models.py|src/offerpilot/db.py|web/|src/offerpilot/api.py|src/offerpilot/ai/)' }) {
  throw 'Interview preparation lease heartbeat changed a forbidden API, schema, frontend, or AI contract file.'
}
~~~

The allowed product-code changes are limited to the repository implementation and the three named test files. The design and plan documents are documentation-only changes. Do not expand the product scope or add any other product-code file.

- [ ] Step 2: Run static checks.

~~~powershell
uv run ruff check src tests
uv run mypy src
git diff --check 6c712eb..HEAD
~~~

Expected result: all commands exit 0.

- [ ] Step 3: Run the complete interview-preparation suite.

~~~powershell
uv run pytest tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py tests/test_interview_preparation_ai.py tests/test_interview_preparation_migrations.py tests/test_smoke.py -q
~~~

Expected result: exit 0; any Windows symlink skip must remain within the repository’s already defined allowlist and must not be added for this task.

- [ ] Step 4: Commit only if static/repository changes were needed.

~~~powershell
git add src/offerpilot/repositories/interview_preparation_proposals.py tests/test_interview_preparation_repository.py tests/test_interview_preparation_api.py tests/test_interview_preparation_ai.py tests/test_interview_preparation_migrations.py tests/test_smoke.py
git commit -m "chore: AI verify interview preparation lease boundary"
~~~

If no files changed in this step, do not create an empty commit.

## Task 7: Isolated local and real-AI acceptance

**Files:**
- Modify only the release verification record if the repository’s existing release process requires it.
- Do not store secrets, JD text, resume text, model output, or full request bodies.

- [ ] Step 1: Run local isolated verification.

~~~powershell
uv run oc verify --profile local --static-dir web/dist
~~~

Expected result: exit 0, temporary data is isolated, and the source data directory is byte-for-byte unchanged.

- [ ] Step 2: Run the focused interview-preparation real-AI verification with the existing configuration.

Use a silent temporary copy of the existing configuration and temporary data directory. Record only model, provider endpoint scheme/host/port, request body byte count, elapsed time, timeout/HTTP category, and hashed Provider request id. Do not print or persist the configuration contents.

The successful evidence must show one Attempt, one Provider call, and a final 200/201 ready result after the slow Provider call. A 202 after lease expiration is a failure of this task. A Provider timeout or network unknown result must remain the existing safe retry state and must be reported as a failed acceptance, not converted to ready.

- [ ] Step 3: Run the complete real-AI verification.

~~~powershell
uv run oc verify --profile real-ai --static-dir web/dist
~~~

Expected result: exit 0. If the real Provider remains unstable, report the exact redacted failure category and stop; do not expand retries, change evidence validation, or claim release readiness.

- [ ] Step 4: Clean all temporary resources.

Confirm the temporary database, service, worker thread, heartbeat sessions, proxy, browser resources, and configuration copy are removed. Confirm no source data files changed and no secrets were emitted.

- [ ] Step 5: Perform an independent code review.

Review the final diff against the design document. Specifically check that:
- only confirmed_ownership_lost blocks the final write before CAS;
- heartbeat_uncertain still reaches final fencing CAS;
- final CAS has no lease-expiry predicate;
- status, revision, token, and source fingerprint remain predicates;
- no Provider call occurs in heartbeat code;
- all heartbeat sessions and workers are closed;
- no API, migration, frontend, AI schema, Offer, or cross-domain behavior changed.

- [ ] Step 6: Final working-tree gate.

~~~powershell
git status --short --branch
git diff --check 6c712eb..HEAD
~~~

Expected result: clean working tree and zero diff-check errors. Do not push or merge.

## Commit sequence

Use the following English conventional commit titles, each with the required AI prefix:

1. test: AI add interview preparation lease timing seams
2. feat: AI keep interview preparation lease alive
3. fix: AI fence late interview preparation results
4. test: AI cover interview preparation takeover fencing
5. test: AI preserve interview preparation failure cleanup
6. chore: AI verify interview preparation lease boundary

Only create a commit when that task has an actual diff. Do not amend or rewrite existing commits. Do not push or merge this branch.
