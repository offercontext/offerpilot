# OfferPilot Write Operation Ledger Phase 3 Code Review

## Final readiness decision

**No-Go for release.** No P0 or P1 remains. P1-03 through P1-08 and P2-06 through P2-09 are closed with focused code and test evidence, but new P2-10 remains in the primary deterministic-failure commit path.

Open at this HEAD: **P2-10 only; no P0/P1**. The normal success, rejection, legacy, and compensation commit-site mappings are covered, but `_commit_failure()` still bypasses the phase-aware commit-site reconciliation.

## Reviewed scope and method

- Fixed baseline: `5e560580e86da7d1eb272e0df9d3d13304717499`.
- Implementation HEAD: `1ad4d24` (`fix: AI distinguish ledger reconciliation states`).
- Included prior commit-unknown reconciliation fix: `2fb7bab` (`fix: AI reconcile ledger commit unknown`).
- Included acceptance/concurrency commit: `c2c564a` (`test: AI cover ledger concurrency recovery`).
- Included latest migration compatibility fix: `bdb32cd` (`fix: AI rebuild ledger chat schema with stale triggers`).
- Previous reviewed implementation: `b358c66`.
- Schema atomicity/index fix reviewed: `ff43823`.
- Included migration compatibility commit: `5d9b88a` (`fix: AI support legacy chat ledger migration`).
- Prior review update: `6c55fce`.
- Compared the current source/tests with `docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md` and `docs/superpowers/plans/2026-08-19-write-operation-ledger.md`.
- Inspected the Ledger coordinator/repository, API/SSE confirmation paths, Journal boundary, models, SQLite migration, and focused tests. Reproduced both a valid old-schema upgrade and a malformed orphan-row upgrade with temporary databases. No product source was changed by this review; only this report is updated.
- Confirmed `tests/test_ai_agent.py` contains no skipped or `_retired_` persistent-checkpoint bodies at this HEAD; the removed checkpoint tests are not retained as dead collection-free test code.
- The full long gate was intentionally not run because the parent task owns it.

Severity: P1 blocks release because behavior can violate a required Phase 3 guarantee. P2 is a material integrity, performance, contract, or acceptance gap.

## Severity summary

- P0: none observed.
- P1: P1-03 through P1-08 resolved with evidence.
- P2: P2-06 through P2-09 resolved; P2-10 open.
- P3: none requiring a report finding.

## Previous open findings: resolution evidence

### P1-03 — 0025 upgrade ChatMessage constraints/FK

**Resolved for a valid 0025-shaped database.** The migration now adds legacy columns and calls the real table rebuild at `src/offerpilot/db.py:1198-1208`. `_rebuild_chat_messages_for_write_operation_integrity()` creates both delivery CHECK constraints and the conversation/operation foreign keys at `src/offerpilot/db.py:1586-1642`, copies legacy rows, and restores the table at `:1645-1659`. `tests/test_schema_compatibility.py:246-280` now initializes twice and checks the table SQL and operation FK.

A read-only old-schema fixture initialized twice at this HEAD reported both CHECK names and the operation FK. The original deployment-dependent integrity gap is closed. The malformed-data failure mode found below is tracked separately as P1-07.

### P1-04 — Authoritative fallback event ordering and operation identity

**Resolved.** The SSE path buffers the pending origin `tool_result` at `src/offerpilot/api.py:7027-7047`. Normal continuation/final delivery releases it only after persistence at `:7334`, `:7381`, and `:7449`; timeout and ordinary-exception fallback now release it at `:7126-7131` and `:7239-7244`. `_confirmation_fallback_response()` includes `operation_id` and `replayed` at `src/offerpilot/api.py:10840-10857`, and `_persist_confirmation_fallback()` supplies the pending operation id at `:10810-10815`.

The sync and SSE provider-error/fallback tests now assert the response operation id and exactly one origin event with the same id (`tests/test_chat_api.py:4768-4777` and `:6031-6051`). Cancellation/stale/error paths intentionally do not claim a successful authoritative delivery. The prior successful-fallback ordering/identity defect is closed.

### P1-05 — Journal draft transaction boundary and terminal renderer fallback

**Resolved for the Ledger write path.** `prepare_call()` prepares the `tool.started` draft before coordinator entry (`src/offerpilot/ai/tool_runtime/pipeline.py:119-135`). The coordinator inserts that prebuilt draft through a SAVEPOINT at `src/offerpilot/ai/write_operations.py:967-971`; `SafeRunRecorder.append_prepared_event_bound()` only inserts the supplied draft at `src/offerpilot/agent_runtime/journal.py:354-371`, and `AgentRunRepository.append_event_bound()` no longer canonicalizes/recomputes it (`src/offerpilot/repositories/agent_runs.py:346-357`). Thus canonical JSON, digest, dedupe, and key-domain preparation occur outside the business transaction.

Terminal result/transport projections are built and persisted before terminal commit (`src/offerpilot/ai/write_operations.py:993-1018`). The Ledger executor path now requires the persisted visible result and passes it to the post-commit Journal projector without `render_compatibility()` fallback (`src/offerpilot/ai/tool_runtime/pipeline.py:178-193`). Agent response/event emission likewise requires persisted terminal fields (`src/offerpilot/ai/agent.py:697-706` and `:790-804`). The remaining renderer calls in the generic non-Ledger read/failure pipeline are outside this Ledger terminal path. The prior post-commit recompute and in-transaction draft-preparation defects are closed.

### P1-06 — Conversation deletion during expired delivery takeover

**Resolved as a controlled unknown outcome.** `converge_expired_delivery()` now checks for a deleted conversation before constructing ChatMessage rows (`src/offerpilot/ai/write_operations.py:753-766`) and returns non-retryable `operation_delivery_unknown` rather than allowing a NULL `conversation_id` integrity exception. The regression test at `tests/test_write_operations.py:331-341` deletes the conversation, expires the lease, and verifies the controlled result. Operation truth remains in the Ledger; no fake delivery is written.

### P2-06 — Compensation parent terminal digest format

**Resolved.** `ck_write_operations_sha256_digests` now validates `parent_terminal_payload_sha256` as a 71-character `sha256:` hex digest (`src/offerpilot/models.py:1713-1723`). Existing-database insert/update backstop triggers apply the same check and require equality with the parent terminal digest (`src/offerpilot/db.py:1264-1277` and `:1326-1339`). The migration compatibility test also checks the resulting operation table SQL at `tests/test_schema_compatibility.py:277-280`.

## Remaining and new findings

### P1-07 — ChatMessage rebuild atomicity

**Resolved.** The rebuild now validates the temporary table before dropping or renaming the legacy table (`src/offerpilot/db.py:1658-1664`), creates `idx_chat_messages_conv` before commit (`:1665-1668`), and only then commits. A failed `foreign_key_check` is therefore rolled back by the handler at `:1670-1672` without swapping the old table or recording migration 0026.

`tests/test_schema_compatibility.py:301-355` reproduces an orphan-row upgrade twice and requires both attempts to fail, the old table to remain without the new CHECK constraints, and `0026_write_operation_ledger` to remain absent. This closes the previously observed retry-success/data-corruption window.

### P1-08 — Commit-unknown terminal writes skip fresh-session reconciliation

**Resolved for terminal commit-unknown.** Design §16.1 requires a `session.commit()` exception to discard the current Session and fresh-read the operation. If the terminal row and integrity checks are present, the request must replay/recover the durable result (and use the delivery fence when needed), without rerunning the executor (`docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md:807-819`).

The coordinator now routes OperationalError from primary, rejection, legacy, and compensation through `_reconcile_commit_unknown()` at `src/offerpilot/ai/write_operations.py:1060-1071`, `:1146-1154`, `:1258-1266`, and `:1438-1446`. The helper opens a fresh Session, reads the authoritative Ledger row, and calls `repository.replay()` for a valid terminal row at `:1462-1482`. This supplies the required first-call terminal replay without using Pending args, rerunning the executor, or rerunning Provider/read tools.

The updated matrix injects “commit succeeds, response is lost” at `tests/test_write_operation_acceptance_matrix.py:373-409` and `:467-517`, and now requires the first call to return `OperationReplay`; a second call also replays and each executor runs once. The focused write/matrix run passed 38 tests. The nonterminal branch mapping is covered separately under P2-09 below.

### P2-09 — Commit-unknown nonterminal branch mapping and coverage

**Resolved.** Commit-site catches now pass role/phase-specific codes while the outer catches retain `operation_busy` for non-commit lock/contention failures. Primary/rejection/legacy terminal commits use absent=`operation_result_unknown`, proposed=`operation_not_committed` at `src/offerpilot/ai/write_operations.py:1060-1084`, `:1146-1164`, and `:1258-1278`; compensation proposal commits use absent/proposed=`operation_not_committed` at `:1336-1359`, and compensation execution commits use absent=`operation_result_unknown`, proposed=`operation_not_committed` at `:1438-1458`. `_reconcile_commit_unknown()` returns the supplied absent/proposed code and maps a fresh-read OperationalError to `operation_result_unknown` at `:1462-1482`. These branches match design §16/§18 (`docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md:809-817` and `:911-928`).

`tests/test_write_operation_acceptance_matrix.py:412-464` now executes the primary proposed/absent, compensation proposal/execution absent, and unreadable fresh-read cases and asserts the required codes. The actual primary and compensation commit-response-loss tests at `:373-409` and `:467-517` require first-call `OperationReplay` with one executor call; code inspection confirms the rejection and legacy commit sites use the same terminal mapping. Non-commit writer-lock paths remain on the outer `operation_busy` handlers. P2-09 is closed.

### P2-10 — Primary deterministic-failure commit bypasses phase-aware reconciliation

**Open; release-blocking acceptance gap.** The normal primary success path now catches its terminal `session.commit()` at `src/offerpilot/ai/write_operations.py:1060-1071`, but `_commit_failure()` is also a primary terminal commit site and still calls `session.commit()` directly at `:1539-1576`. A commit response loss from a validator/domain deterministic failure therefore escapes to the outer handler at `:1073-1084`, which supplies `proposed_code="operation_busy"` rather than the commit-site `operation_not_committed`. If that failed terminal transaction is not durable and the fresh read sees the still-proposed operation, the observable code violates §16.1; the current matrix only injects response loss for the success path and its branch test calls the private helper directly, so it cannot catch this wiring omission.

Wrap `_commit_failure()`'s commit at the commit site with the same absent=`operation_result_unknown`, proposed=`operation_not_committed` reconciliation and add a mapped validator/domain-failure commit-response-loss test asserting terminal replay when durable, proposed code when not durable, and one executor call.

### P2-07 — Required adapter/concurrency acceptance matrix

**Resolved as an executable coverage gap.** `tests/test_write_operation_acceptance_matrix.py` now has 25 passing cases: `:165-200` enumerates all 12 typed adapters with one executor call and replay, `:203-228` covers all 3 legacy adapters, `:231-278` covers all 4 compensation kinds, `:281-337` covers late-owner fencing plus message/manifest tamper rejection, `:340-370` races two primary connections, `:373-409` injects primary commit response loss, `:412-464` covers reconciliation branches, `:467-541` covers compensation commit response loss and stable deterministic parent conflict, and `:544-582` races two expired delivery takeovers. The matrix file now passes both Ruff and strict mypy (`# mypy: disable-error-code` is limited to the test file's untyped test helpers).

The direct matrix intentionally isolates Ledger coordinator behavior: it replaces catalog executors with spies and uses `NullRunRecorder`. The required runtime integration is covered by the existing API goldens, so this harness scope is no longer an open P2. `tests/test_chat_api.py:1040-1117` runs deterministic confirmation retry for both sync and SSE, verifies delivery takeover replay, exactly one domain version, and `model.calls == 0`; `:5919-5990` runs the unrelated-generation race for both sync/SSE, verifies the single SSE origin event carries the operation id, and verifies the chained Pending, persisted history, and unchanged domain result. Those four focused API cases pass, so duplicating them in the Ledger-only matrix is unnecessary.

The commit-unknown tests now close both the terminal replay and nonterminal branch portions of P1-08/P2-09. Parent digest/trigger enforcement remains covered by the schema and compensation integrity tests described under P2-06. Therefore P2-07 is closed.

### P2-08 — Legacy ChatMessage rebuild index retention

**Resolved.** The replacement table now recreates `idx_chat_messages_conv` before commit at `src/offerpilot/db.py:1665-1668`. The valid upgrade test asserts that index alongside the operation/ordinal index (`tests/test_schema_compatibility.py:273-298`), and the twice-initialized old-schema fixture verified it is retained.

## Verification performed

- `uv run pytest tests/test_write_operations.py tests/test_write_operation_acceptance_matrix.py -q` — **38 passed**, 1 warning.
- `uv run pytest tests/test_schema_compatibility.py tests/test_write_operation_acceptance_matrix.py -q` — **39 passed**, 1 warning.
- `uv run pytest tests/test_chat_api.py -q -k "deterministic_pilot_retries_same_key_after_chat_cas_failure or chat_confirm_ledger_delivery_survives_unrelated_conversation_generation_change"` — **4 passed**, 290 deselected, 25 warnings.
- `uv run pytest tests/test_chat_api.py -q -k "confirm_stream_executes_pending_write_and_completes or chat_confirm_stream_recovers_committed_write_when_followup_model_fails or chat_confirm_ledger_delivery_persists_fallback_after_generation_change or chat_confirm_rejection_provider_failure_records_cancellation_once or chat_confirm_result_cas_loss_stays_stale_on_followup_failure or chat_confirm_tool_error_provider_failure_is_durable"` — **12 passed**, 282 deselected, 97 warnings.
- `uv run ruff check` on the ten changed Ledger/API/schema/Journal modules — passed.
- `uv run mypy` on those ten modules — passed with no issues.
- `uv run ruff check tests/test_write_operation_acceptance_matrix.py` — passed.
- `uv run mypy tests/test_write_operation_acceptance_matrix.py` — **Success: no issues found in 1 source file**.
- `uv run mypy src` — **Success: no issues found in 104 source files**.
- Valid old-schema temporary database, initialized twice — CHECKs, operation FK, and both expected indexes present; data readable; `0026` initialization idempotent.
- Malformed orphan-row temporary database — two initialization attempts both failed before table swap and without recording `0026`.
- Full long release gate — not run; owned by the parent task.

## Final decision

**No-Go.** P1-03 through P1-08 and P2-06 through P2-09 are closed with code/test evidence. No P0/P1 remains, but P2-10 is open because the deterministic primary-failure terminal commit still bypasses phase-aware commit-unknown reconciliation. The full long release gate is intentionally not repeated here and remains the parent task’s responsibility.
