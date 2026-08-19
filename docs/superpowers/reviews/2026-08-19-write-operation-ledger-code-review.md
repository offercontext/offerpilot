# OfferPilot Write Operation Ledger Phase 3 Code Review

## Final readiness decision

**Not ready for release.** No P0 was found, and the previously open P1-03, P1-04, P1-05, and P1-06 findings are closed at the normal valid-data/runtime paths. P2-06 is also closed. The re-review found one new P1 migration-atomicity defect and one new P2 migration-schema regression; P2-07 remains open because the required 12 typed + 3 legacy + 4 compensation acceptance matrix is still not executable coverage.

Open at this HEAD: **P1-07, P2-07, and P2-08; no P0**. The migration integrity failure must be fixed before acceptance. The P2 coverage/index items should also be fixed before calling the Phase 3 gate green.

## Reviewed scope and method

- Fixed baseline: `5e560580e86da7d1eb272e0df9d3d13304717499`.
- Implementation HEAD: `4cb9cca` (`fix: AI close ledger delivery review gaps`).
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

### P1-07 — ChatMessage rebuild commits before foreign-key validation

The new rebuild is not atomic on malformed legacy data. It commits the renamed table at `src/offerpilot/db.py:1658-1661`, then runs `PRAGMA foreign_key_check` at `:1661-1664`. If the check finds an orphan, the `RuntimeError` is caught at `:1665-1667`, but the subsequent rollback cannot undo the already completed `raw.commit()`.

This is reproducible: a temporary old-schema database containing a `chat_messages.conversation_id` orphan raised `RuntimeError: chat message foreign key migration failed` on its first initialization, while the rebuilt table and orphan row remained. A second `init_database()` then succeeded and recorded `0026_write_operation_ledger` even though `PRAGMA foreign_key_check(chat_messages)` still reported the orphan. The upgrade must validate before commit (or quarantine/fail without swapping), and a failed migration must not become a recorded successful migration on retry while invalid rows remain.

### P2-07 — Required adapter/concurrency acceptance matrix remains incomplete

The latest changes add useful migration, fallback, and deleted-conversation tests, but the Ledger-specific tests still do not execute the required full matrix from spec §23: all 12 typed adapters, all 3 legacy adapters, all 4 compensation adapters, two-connection executor/takeover/commit-unknown crash points, late-Bundle fencing, replay with zero executor/Provider/read-tool/renderer calls, and full message/manifest tamper cases. `tests/test_write_operations.py:51-341` has manifest/golden identity and focused invariant tests, not one golden execution/replay contract per adapter. This remains an acceptance evidence gap even though the currently targeted tests pass.

### P2-08 — Legacy ChatMessage rebuild drops the conversation index

The model declares `idx_chat_messages_conv` at `src/offerpilot/models.py:1575`, but the replacement table SQL at `src/offerpilot/db.py:1615-1642` does not create it and the post-rename migration at `:1658-1659` does not recreate it. A read-only valid old-schema upgrade followed by `PRAGMA index_list(chat_messages)` returned only `uq_chat_messages_operation_ordinal`; the conversation index was lost. This can turn normal conversation message loads into table scans on upgraded databases. Recreate the model index as part of the rebuild and assert it in the upgrade test.

## Verification performed

- `uv run pytest tests/test_write_operations.py tests/tool_pipeline/test_checkpoint.py tests/test_schema_compatibility.py -q` — **29 passed**, 1 warning.
- `uv run pytest tests/test_chat_api.py -q -k "confirm_stream_executes_pending_write_and_completes or chat_confirm_stream_recovers_committed_write_when_followup_model_fails or chat_confirm_ledger_delivery_persists_fallback_after_generation_change or chat_confirm_rejection_provider_failure_records_cancellation_once or chat_confirm_result_cas_loss_stays_stale_on_followup_failure or chat_confirm_tool_error_provider_failure_is_durable"` — **12 passed**, 282 deselected, 97 warnings.
- `uv run ruff check` on the ten changed Ledger/API/schema/Journal modules — passed.
- `uv run mypy` on those ten modules — passed with no issues.
- Valid old-schema temporary database, initialized twice — CHECKs and operation FK present; data readable; `0026` initialization idempotent. The same fixture exposed P2-08 because only the operation/ordinal index remained.
- Malformed orphan-row temporary database — reproduced P1-07: first initialization failed after the rebuild commit, and retry recorded the migration while the FK violation remained.
- Full long release gate — not run; owned by the parent task.

## Final decision

**Not ready.** P1-03, P1-04, P1-05, P1-06, and P2-06 are closed with code/test evidence. P1-07 is a new migration atomicity/integrity blocker; P2-07 leaves the required adapter and concurrency acceptance behavior unproven; P2-08 loses a required production index during valid legacy upgrade. No P0 was found.
