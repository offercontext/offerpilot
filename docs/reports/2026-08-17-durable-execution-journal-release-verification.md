# Durable Execution Journal Release Verification

Date: 2026-08-18

Branch: `feat/20260817-durable-execution-journal`

Fixed baseline: `dd083a950b403bd96da02999413d4c2aa6233c50`

## Scope and allowlist

This phase adds a fail-open diagnostic execution journal around the existing Agent runtime. It does not make the Journal a business source of truth and does not change the existing Conversation, Pending Action, confirmation, Provider, SSE, or domain-write contracts.

The immutable positive allowlist contained these paths:

- `src/offerpilot/models.py`
- `src/offerpilot/db.py`
- `src/offerpilot/repositories/agent_runs.py`
- `src/offerpilot/agent_runtime/__init__.py`
- `src/offerpilot/agent_runtime/events.py`
- `src/offerpilot/agent_runtime/journal.py`
- `src/offerpilot/agent_runtime/keyring.py`
- `src/offerpilot/agent_runtime/trace.py`
- `src/offerpilot/api.py`
- `src/offerpilot/ai/agent.py`
- `tests/test_agent_run_migrations.py`
- `tests/test_agent_runs_repository.py`
- `tests/test_agent_run_journal.py`
- `tests/test_agent_run_keyring.py`
- `tests/test_agent_run_trace.py`
- `tests/test_ai_agent.py`
- `tests/test_chat_api.py`
- `tests/test_settings_api.py`
- `tests/test_smoke.py`
- `docs/reports/2026-08-17-durable-execution-journal-release-verification.md`

The final pre-report scope assertion found zero changed paths outside this allowlist. A diagnostic cleanup change outside the allowlist was committed and immediately reverted; it has no net baseline diff and the allowlist remained unchanged.

## Delivered behavior

- Added the `AgentRun`, `AgentEvent`, and `AgentContextSnapshot` models and migration `0024_durable_execution_journal`.
- Added an independent, atomically created Journal HMAC key domain with bounded permission handling, backup exclusion, concurrent creation protection, and fail-open startup.
- Added strict canonical event and context contracts, complete stable-event digests, bounded manifests, source-reference validation, UUID constraints, and 4 KiB event / 16 KiB snapshot database limits.
- Added an atomic repository with monotonic sequence allocation, idempotent dedupe, conflict detection, snapshot/event atomicity, terminal immutability, waiting-run lookup, and bounded SQLite lock behavior.
- Added `SafeRunRecorder`, `NullRunRecorder`, a degraded latch, 150 ms segment budgets, 50 ms final-disposition convergence, and deterministic trace reconstruction with separate lifecycle, completion, stale, suspension, terminal, and integrity classifications.
- Instrumented model calls and tool-call facts without recording prompts, answers, credentials, job-description text, resume text, or arbitrary context strings.
- Connected ordinary JSON Chat, SSE Chat, deterministic actions, and confirmation resume to the same logical Run while preserving existing business CAS, fencing, and confirmation semantics.
- Added behavior-equivalence coverage for Journal enabled, disabled, degraded, and failed paths.

There are no public API, CLI, UI, SSE envelope, Provider, or business-domain schema changes. The only database change is the three diagnostic Journal tables and their indexes/constraints.

## Commits

- `655fd44 feat: AI add durable journal key domain`
- `d318b6e feat: AI add durable agent journal schema`
- `32426d6 feat: AI add durable journal event contracts`
- `f6a74b7 fix: AI harden durable journal privacy boundaries`
- `7154565 fix: AI align durable journal event contracts`
- `c0fb8a8 fix: AI close durable journal batch one review`
- `2934450 feat: AI add atomic durable journal repository`
- `2fbdbf6 fix: AI harden durable journal repository review`
- `a5126c9 feat: AI add safe journal recorder and trace`
- `3369877 fix: AI satisfy durable journal type gate`
- `493fd7c feat: AI instrument agent model and tool runs`
- `e28bab3 feat: AI journal chat execution lifecycle`
- `fec5faf feat: AI journal confirmation resume lifecycle`
- `125020e test: AI verify durable journal equivalence`
- `39947a6 fix: AI harden durable journal lifecycle convergence`
- `8df478f test: AI make journal key gate platform neutral`
- `c110892 fix: AI dispose durable journal smoke engine`
- `97d6c31 revert: AI remove out-of-scope smoke cleanup`

The last two commits are a net-zero diagnostic attempt retained in history for auditability; the proposed product-file change was outside the fixed allowlist and was therefore reverted before release reporting.

## Schema and migration verification

- Fresh database initialization created all three Journal tables and recorded migration `0024_durable_execution_journal`.
- Upgrade from a `0023` database recorded `0024` exactly once.
- Foreign-key cascade, rollback, unique constraints, waiting tool-call partial uniqueness, UUID checks, payload limits, and model-call constraints were exercised.
- Journal repository access uses its independent short-timeout SQLite Session/Pool while retaining the existing business database as the authoritative store.

## Focused privacy, repository, trace, and equivalence verification

- The focused acceptance matrix covering keyring, migration, repository, event/privacy contracts, trace, Agent instrumentation, Chat API, settings, and smoke behavior completed with `584 passed, 1 skipped` before the platform-neutral keyring gate adjustment.
- The adjusted keyring suite then completed with `12 passed` and no skip.
- Journal repository/recorder/trace suites completed with `99 passed`.
- Ten targeted lifecycle-convergence regressions passed after the final review fixes.
- `tests/test_smoke.py` completed with `58 passed` during cleanup diagnosis; the exploratory cleanup edit was subsequently reverted to preserve the immutable scope.
- Focused Ruff and Mypy checks passed, and `git diff --check` passed.

The privacy tests cover bounded canonical JSON, HMAC-only sensitive-source representation, manifest truncation/digests, key non-export, backup exclusion, rejection of arbitrary facts, and the event/snapshot byte boundaries. Equivalence tests compare business-visible responses and persisted business state across healthy, disabled, unavailable, and degraded Journal modes.

## Complete backend gate

A fresh duplicate-sensitive manifest contained `2307` unique test node IDs and no duplicates. The grouped aggregate covered the same `2307` tests:

| Group | Collected | Tests | Skipped | Failures | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| agent | 495 | 495 | 0 | 0 | 0 |
| domain | 73 | 73 | 0 | 0 | 0 |
| knowledge | 659 | 659 | 4 | 0 | 0 |
| proposals | 431 | 431 | 0 | 0 | 0 |
| misc | 649 | 649 | 0 | 0 | 0 |
| **Total** | **2307** | **2307** | **4** | **0** | **0** |

The four skips are the gate's fixed Windows symlink-permission cases:

- failed ingest cleanup does not follow a symlink;
- Knowledge reset rejects a symlinked root;
- legacy reset rejects a symlinked root;
- Knowledge reset does not follow a nested escaping symlink.

No Journal test remained skipped.

## Complete frontend gate

The frontend manifest contained `166` test files and fingerprinted `424` source/configuration files. Its manifest SHA-256 was `688778f3b0dd31216bb17362cbaf681a7b1543026163537819f96e4939985ab2`; its source SHA-256 was `103f5f777f33d3841ca5958ced8d45f6ceb5807b170d4d249d6498e651ba5617`.

| Group | Files | Tests |
| --- | ---: | ---: |
| components-core | 35 | 186 |
| components-chat | 14 | 195 |
| components-interview | 15 | 86 |
| components-offer | 8 | 45 |
| components-support | 8 | 32 |
| features | 42 | 321 |
| layout | 14 | 87 |
| lib | 14 | 199 |
| services | 15 | 67 |
| theme | 1 | 4 |
| **Total** | **166** | **1222** |

All `1222` tests passed. The aggregate contained no skipped, pending, or todo tests, and all ten groups shared the same manifest and source fingerprint.

## Static, build, and smoke gates

- `uv run ruff check .`: passed.
- `uv run mypy src`: passed for 83 source files.
- `npm.cmd run build`: passed; 3942 modules transformed.
- `uv run oc smoke --static-dir web/dist`: passed.
- `scripts/local-smoke.ps1 -Port 18765`: passed.
- `uv run oc verify --profile local --static-dir web/dist`: passed.
- `uv run oc verify --profile real-ai --static-dir web/dist`: **did not pass**. The single permitted run exited during Windows temporary-database cleanup because the database file still had an open handle. No Provider failure was reported, but the run is treated as failed/indeterminate because cleanup did not complete. It was not retried.

The frontend build retained an existing large-chunk warning. Installing the exact locked frontend dependencies for the gate reported existing package-audit findings; dependency remediation was outside this allowlist.

## Independent review

Independent review examined the baseline-to-branch diff, all allowlisted product/test files, and the special privacy, atomicity, timeout, confirmation, SSE identity, and equivalence targets.

Issues found and resolved included:

- normalized the tool-shape digest format;
- prevented stale key locks from being removed unless owner death was established;
- added database UUID constraints for model-call references;
- hardened key-domain consistency and idempotent disposition convergence;
- separated historical waiting events from the current trace lifecycle;
- made stale/CAS-losing confirmation segments abandon their own segment without terminalizing the shared Run;
- converged delayed confirmation success and failure after request timeout;
- preserved terminal winners while closing replay/no-op segments.

After fixes, the reviewer reported no remaining P0, P1, P2, or P3 findings. A separate review of the exploratory smoke-cleanup patch also found no code issue, but that patch was reverted solely because the product file was outside the fixed allowlist.

## External/transient failures encountered

- One proposals-group attempt saw a dedicated Chromium process exit before readiness. The exact isolated test passed, and the full proposals group then passed all 431 tests.
- The initial frontend command could not start before locked dependencies were installed. `npm ci` restored the declared environment; all frontend groups and the build then passed.
- The real-AI gate encountered the unresolved Windows temporary-database handle described above. This is the only final gate that did not pass.

## Breaking changes and remaining risks

There are no intended breaking changes to public or business behavior. The migration adds diagnostic tables to existing databases; removing the feature would require deciding separately whether to retain or delete those diagnostic rows.

Remaining risks:

- Remote-Provider end-to-end acceptance is not complete because the sole bounded real-AI verification exited during cleanup. The application behavior preceding cleanup produced no reported Provider error, but that is not sufficient to mark the gate passed.
- The observed open-handle cleanup path is outside this phase's immutable product allowlist. It needs a separately scoped fix and a newly authorized real-AI verification if release policy requires a fully green real-AI gate.
- Existing frontend dependency audit findings and the large production bundle warning remain outside this phase.
- The Journal intentionally remains fail-open diagnostic data. It does not provide business exactly-once, event sourcing, SSE replay, UI inspection, ToolSpec, Write Operation Ledger, or Context Projector behavior.

## Verdict

Tasks 6-9 and the implementation/review portions of Task 10 satisfy their scoped acceptance criteria. Complete backend, frontend, static, build, local smoke, and local verification gates passed. Release acceptance is **conditional rather than fully green** because the single real-AI verification did not exit successfully; the exact failure and required follow-up are recorded above.
