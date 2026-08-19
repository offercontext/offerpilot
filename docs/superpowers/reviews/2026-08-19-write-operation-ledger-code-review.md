# OfferPilot Write Operation Ledger Phase 3 Code Review

## Final readiness decision

**No-Go for release.** No P0 or P1 remains. P1-03, P1-04, P1-05, P1-06, and P1-07 are closed with focused code and test evidence; P2-06 and P2-08 are also closed. P2-07 remains open because the required 12 typed + 3 legacy + 4 compensation acceptance matrix is still not executable coverage.

Open at this HEAD: **P2-07 only; no P0/P1**. P2-07 is still a completion blocker under the design’s independent-CR acceptance requirement; the code-level migration, delivery, fencing, and Journal blockers are closed.

## Reviewed scope and method

- Fixed baseline: `5e560580e86da7d1eb272e0df9d3d13304717499`.
- Implementation HEAD: `b358c66` (`test: AI add ledger acceptance matrix`).
- Previous reviewed implementation: `4cb9cca`.
- Schema atomicity/index fix reviewed: `ff43823`.
- Included migration compatibility commit: `5d9b88a` (`fix: AI support legacy chat ledger migration`).
- Prior review update: `6c55fce`.
- Compared the current source/tests with `docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md` and `docs/superpowers/plans/2026-08-19-write-operation-ledger.md`.
- Inspected the Ledger coordinator/repository, API/SSE confirmation paths, Journal boundary, models, SQLite migration, and focused tests. Reproduced both a valid old-schema upgrade and a malformed orphan-row upgrade with temporary databases. No product source was changed by this review; only this report is updated.
- The full long gate was intentionally not run because the parent task owns it.

Severity: P1 blocks release because behavior can violate a required Phase 3 guarantee. P2 is a material integrity, performance, contract, or acceptance gap.

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

### P2-07 — Required adapter/concurrency acceptance matrix remains incomplete

**Partially resolved; P2 remains open.** `tests/test_write_operation_acceptance_matrix.py:158-271` now provides 19 parameterized Ledger coordinator cases (12 typed + 3 legacy + 4 compensation), with one executor call and same-operation replay. `:274-330` adds a sequential expired-owner takeover, late-owner fence, message immutability, and manifest immutability case. The new file passes 20 tests, so the prior absence of adapter enumeration and basic replay evidence is closed.

It is not yet the full acceptance matrix required by spec §23. The new adapter tests replace each executor with a trivial function, use `NullRunRecorder`, call the coordinator directly, and do not prove the actual domain projection, sync/SSE replay, declared-failure replay, exact transition/domain-row assertions, or Provider/read-tool call counts. The remaining minimum executable scenarios are:

- two connections racing one proposed operation, proving one executor/domain commit and one loser replay/conflict;
- a primary and compensation commit-unknown injection, proving fresh-session reconciliation never runs the executor twice;
- two expired delivery owners racing takeover, proving one generation-2 CAS winner and one loser with no duplicate messages;
- an actual continuation/replay spy proving Provider/read-tool/renderer calls are zero after terminal commit, delivery recovery, and SSE replay;
- one compensation parent mutation/conflict between proposal and execution, plus one chained-Pending delivery-manifest/transition reconciliation case.

Until these minimum concurrency, commit-unknown, runtime-call, and compensation/chained-delivery cases are executable, P2-07 remains a completion blocker even though the 19 adapter cases pass.

### P2-08 — Legacy ChatMessage rebuild index retention

**Resolved.** The replacement table now recreates `idx_chat_messages_conv` before commit at `src/offerpilot/db.py:1665-1668`. The valid upgrade test asserts that index alongside the operation/ordinal index (`tests/test_schema_compatibility.py:273-298`), and the twice-initialized old-schema fixture verified it is retained.

## Verification performed

- `uv run pytest tests/test_write_operations.py tests/tool_pipeline/test_checkpoint.py tests/test_schema_compatibility.py -q` — **30 passed**, 1 warning.
- `uv run pytest tests/test_write_operation_acceptance_matrix.py -q` — **20 passed**, 1 warning.
- `uv run pytest tests/test_chat_api.py -q -k "confirm_stream_executes_pending_write_and_completes or chat_confirm_stream_recovers_committed_write_when_followup_model_fails or chat_confirm_ledger_delivery_persists_fallback_after_generation_change or chat_confirm_rejection_provider_failure_records_cancellation_once or chat_confirm_result_cas_loss_stays_stale_on_followup_failure or chat_confirm_tool_error_provider_failure_is_durable"` — **12 passed**, 282 deselected, 97 warnings.
- `uv run ruff check` on the ten changed Ledger/API/schema/Journal modules — passed.
- `uv run mypy` on those ten modules — passed with no issues.
- `uv run ruff check tests/test_write_operation_acceptance_matrix.py` — passed. The new test file is not mypy-clean under the repository’s strict settings (17 `no-untyped-def`/related errors); production-source mypy remains clean. This is additional test-quality debt, not a product-runtime failure.
- Valid old-schema temporary database, initialized twice — CHECKs, operation FK, and both expected indexes present; data readable; `0026` initialization idempotent.
- Malformed orphan-row temporary database — two initialization attempts both failed before table swap and without recording `0026`.
- Full long release gate — not run; owned by the parent task.

## Final decision

**No-Go.** P1-03, P1-04, P1-05, P1-06, P1-07, P2-06, and P2-08 are closed with code/test evidence. P2-07 is improved but remains: the required concurrency, commit-unknown, runtime-call, compensation-conflict, and chained-delivery acceptance behavior is not fully represented by executable Ledger-specific goldens. No P0/P1 was found, but the design explicitly requires an independent CR with no P0/P1/P2, so the Phase 3 gate is not green until P2-07 is closed or formally accepted by the release owner.
