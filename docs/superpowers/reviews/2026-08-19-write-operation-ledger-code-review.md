# OfferPilot Write Operation Ledger Phase 3 Code Review

## Re-review decision

**Not ready for release.** No P0 finding was identified. The latest implementation closes P1-01 and P1-02 and all original P2-01..05 findings, but P1-03, P1-04, and P1-05 remain only partially fixed. This review also found a new P1-06 delivery-recovery failure and two P2 gaps. The open P1 items affect upgrade integrity, authoritative response delivery, transaction atomicity, and takeover after conversation deletion.

There are therefore four open P1 findings (P1-03, P1-04, P1-05, P1-06), two new P2 findings, and no P0 findings. Phase 3 should not be accepted until the open P1 behavior is corrected and covered by focused regression tests.

## Reviewed scope and method

- Fixed baseline: `5e560580e86da7d1eb272e0df9d3d13304717499`.
- Original implementation under review: `3b9e964ddf917cf79859fb31161744b84985b3db`.
- Re-review implementation HEAD: `11ec862` (`fix: AI harden write operation ledger acceptance`).
- Previous review report: `53b78c4` (`docs: AI add phase3 ledger code review`).
- Compared the current diff and behavior with `docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md` and `docs/superpowers/plans/2026-08-19-write-operation-ledger.md`.
- Inspected the Ledger coordinator/repository, Chat repository, domain bindings, migration/schema, API and SSE confirmation paths, Agent runner, tool pipeline, Journal, models, and focused tests. A read-only 0025-shaped migration fixture was also exercised. The full long release gate was not run.
- The worktree was clean before this report-only update. No product source was modified by this review.

Severity: P1 blocks release because behavior can violate a required Phase 3 guarantee. P2 is a material integrity, security, contract, or acceptance gap. P3 is lower-risk hardening or cleanup.

## Original findings: resolution evidence

### P1-01 — Delivery heartbeat hard stop

**Resolved.** `src/offerpilot/ai/write_operations.py:95-154` now loops until the stop event, fencing, or an exception; it no longer uses a fixed monotonic deadline. `tests/test_write_operations.py:124-150` verifies repeated renewals (`[1, 2, 3]`) while the owner remains active. This closes the prior 120-second cutoff and satisfies the scoped-heartbeat lifecycle requirement.

### P1-02 — Concurrent first-use Ledger-key creation

**Resolved for the identified race.** `src/offerpilot/ai/write_operations.py:207-258` rechecks both the key file and operation count after acquiring the O_EXCL lock (`:229-234`) before generating a key. `tests/test_write_operations.py:102-121` simulates another writer creating the key immediately after lock acquisition and verifies the existing seed key is retained. The original post-lock overwrite race is closed.

### P1-03 — 0025 upgrade ChatMessage constraints/FK

**Partially resolved; P1 remains open.** The migration now adds columns, backfills compensation digests, rejects invalid legacy delivery rows, installs the operation/ordinal unique index, and installs cross-row insert/update triggers (`src/offerpilot/db.py:1195-1253` and `:1255-1462`). This improves operational validation.

However, `_ensure_write_operation_ledger_schema()` still only calls `_ensure_column()` for an existing `chat_messages` table (`src/offerpilot/db.py:1198-1203`). It does not rebuild or otherwise add the model-defined ChatMessage CHECK constraints and `write_operations` foreign key. A read-only fixture with an old 0025-shaped `chat_messages` table was initialized at HEAD; `PRAGMA foreign_key_list(chat_messages)` returned `[]`, and the table had no delivery CHECK constraints, while the new triggers were present. Fresh `create_all()` and upgrade behavior therefore remain different. The design requires fresh and 0025-upgrade integrity parity (spec lines 1008-1019 and 1061-1074); add the safe SQLite rebuild/equivalent constraints and an upgrade-shape test.

### P1-04 — Authoritative tool-result event ordering and operation identity

**Partially resolved; P1 remains open.** The normal confirmation flow now defers the origin `tool_result` in `src/offerpilot/api.py:7027-7047`, releases it after the continuation/final delivery persistence at `:7332`, `:7379`, and `:7447`, and attaches the confirmed operation id. `tests/test_chat_api.py:5915-5986` covers sync/stream delivery under an unrelated conversation-generation change and verifies one origin event, the operation id, and ordering before completion.

The fallback/error paths still bypass that release and do not return the operation id. In the SSE timeout fallback, `src/offerpilot/api.py:7108-7131` emits `assistant_message` and `completed` and returns; the generic SSE fallback does the same at `:7224-7243`. The sync timeout and generic fallback return the bare fallback at `:6424-6436` and `:6469-6477`. `_confirmation_fallback_response()` at `src/offerpilot/api.py:10836-10848` contains no `operation_id` or replay marker. The authoritative deferred origin event can therefore be withheld on a successful fallback, and clients cannot correlate the fallback response to the Ledger operation as required by spec §19.2. Add fallback sync/SSE tests and release the buffered origin event (or provide the same durable replay identity) on every successful delivery outcome.

### P1-05 — Journal/render/projector transaction boundary

**Partially resolved; P1 remains open.** The coordinator now records the started projection through the caller Session/SAVEPOINT before executor work (`src/offerpilot/ai/write_operations.py:896-1058`, especially `:964-967`), persists visible/transport representations, and carries `journal_started_recorded` into the pipeline. The agent also prefers persisted visible/transport values (`src/offerpilot/ai/agent.py:697-703` and `:776-797`). This closes the prior fully post-commit started-projection path for the normal non-empty result.

The required prepared-draft boundary is still violated. `src/offerpilot/agent_runtime/journal.py:354-366` calls `_event_preparer()` inside the coordinator-owned transaction, and `src/offerpilot/repositories/agent_runs.py:346-358` revalidates the draft. `validate_event_draft()` rebuilds the event through `prepare_event()` (`src/offerpilot/agent_runtime/events.py:799-830`), which performs canonicalization, digest, dedupe, and fingerprint work. The design requires the EventDraft/key/dedupe identity to be prepared before entering the business transaction and only the prebuilt draft to be inserted inside it (spec lines 613-655). In addition, `src/offerpilot/ai/tool_runtime/pipeline.py:180-187` and `src/offerpilot/ai/agent.py:697-703` retain `or render_compatibility(...)` fallbacks, so an empty/missing persisted value can still cause a post-commit renderer path. Move all preparation outside the transaction and make replay/terminal delivery consume an explicitly persisted representation without fallback recomputation; add a SAVEPOINT-failure and replay-no-render test.

### P2-01 — `ChatRepository.bind()` contract

**Resolved.** `src/offerpilot/repositories/chat.py:34-55` adds `_operation_session()`, and operation proposal, resolution, replacement, and continuation helpers use the caller Session without committing or rolling back when bound (`:271-324`, `:382-480`, `:482-743`). `tests/test_write_operations.py:166-187` persists through a bound repository, rolls back the caller transaction, and verifies no public state remains. The original bypass is closed.

### P2-02 — Compensation parent revalidation

**Resolved.** Proposal records `parent_terminal_payload_sha256` after validating the parent (`src/offerpilot/ai/write_operations.py:1234-1287`). Execution reloads and rechecks parent role, committed status, conversation, undo data, the stored terminal digest, and compensation kind (`:1307-1322`). This closes the originally missing second-phase parent identity checks. A dedicated two-transaction mutation test would still improve evidence, but the identified code defect is fixed.

### P2-03 — Database-enforced transition lifecycle

**Resolved.** `src/offerpilot/db.py:1403-1462` installs an insert trigger enforcing proposal → approval/rejection → claim → terminal sequence/state and matching operation status, plus immutable update/delete triggers. `tests/test_write_operations.py:190-215` rejects an out-of-order direct sequence-3 insert. The prior coordinator-only lifecycle guarantee is now backed by the database.

### P2-04 — Empty primary `tool_call_id`

**Resolved.** `src/offerpilot/models.py:1636-1641` now requires a non-null, non-empty primary `tool_call_id`, and `tests/test_write_operations.py:218-236` verifies an empty id is rejected. The original operation/message identity mismatch is closed.

### P2-05 — Retired persistent-checkpoint test bodies

**Resolved.** The latest diff removes the old skipped/renamed bodies rather than retaining `_retired_*` dead tests. `rg` finds no `_retired` tests or production `SqliteSaver`/checkpoint-path dependency. Remaining checkpoint strings are intentional negative assertions in `tests/test_chat_api.py:5300`, `:5529`, `:5566` and `tests/tool_pipeline/test_checkpoint.py:9-25`. The parent’s concern about retaining dead retired bodies is therefore addressed; no deletion is still requested for this finding.

### P3-01 — Raw delivery-owner token serialization

**Resolved.** `DeliveryOwnership` at `src/offerpilot/ai/write_operations.py:95-124` now keeps the raw token private and exposes only a fingerprint-based public identity. `tests/test_write_operations.py:153-164` verifies safe public identity, redacted repr, and that `dataclasses.asdict()` is not available. The prior generic serialization leak is closed.

## New findings

### P1-06 — Takeover after conversation deletion can crash delivery recovery

`WriteOperation.conversation_id` is nullable with `ON DELETE SET NULL` (`src/offerpilot/models.py:1823-1825`), and `ChatRepository.delete_conversation()` deletes the conversation (`src/offerpilot/repositories/chat.py:907-915`). That is compatible with the design requirement to retain operation truth after conversation deletion.

During expired-delivery convergence, however, `src/offerpilot/ai/write_operations.py:753-857` unconditionally creates the origin and continuation `ChatMessage` rows with `cast(int, operation.conversation_id)` at `:797-820`, then flushes at `:841`. If the conversation was deleted, this is `None` for a non-null ChatMessage foreign key and raises an integrity error. The handler catches only `OperationalError` at `:858-859`, not the resulting integrity error, so replay/takeover can surface a 500 instead of the specified deterministic delivery-unknown/replay outcome. Add a deleted-conversation takeover test and either preserve a valid delivery context or return a controlled terminal result without attempting ChatMessage insertion.

### P2-06 — Compensation parent digest is required by role identity but not format-validated

The compensation branch requires `parent_terminal_payload_sha256 IS NOT NULL` (`src/offerpilot/models.py:1636-1641`), but `ck_write_operations_sha256_digests` validates only `terminal_payload_sha256` and `delivery_manifest_sha256` (`:1713-1720`). A direct compensation insert can therefore carry a malformed non-null parent digest and survive model-level integrity checks until execution-time comparison. Add the same `sha256:` length/hex constraint to the parent digest and a malformed direct-insert test.

### P2-07 — Required acceptance matrix is still incomplete

The current Ledger-specific unit file has ten test functions (`tests/test_write_operations.py:50-244`), and the checkpoint replacement file has three static tests (`tests/tool_pipeline/test_checkpoint.py:9-25`). The focused suite still lacks executable coverage for the 0025-upgrade FK/CHECK shape, all 12 typed + 3 legacy + 4 compensation behavior contracts, two-connection executor/takeover/commit-unknown crash points, long-owner fencing and late Bundle rejection, replay with zero executor/Provider/read-tool/renderer calls, fallback sync/SSE operation-id ordering, deleted-conversation takeover, and the Journal prebuilt-draft boundary. The retired bodies being deleted is correct cleanup, but it does not replace this required Phase 3 acceptance matrix.

## Verification performed

The following focused, read-only checks were run against HEAD `11ec862`:

- `uv run pytest tests/test_write_operations.py tests/tool_pipeline/test_checkpoint.py tests/test_schema_compatibility.py -q` — **29 passed**, 1 warning.
- `uv run pytest tests/test_chat_api.py -q -k "confirm_stream_executes_pending_write_and_completes or chat_confirm_stream_recovers_committed_write_when_followup_model_fails or chat_confirm_ledger_delivery_persists_fallback_after_generation_change or chat_confirm_rejection_provider_failure_records_cancellation_once or chat_confirm_result_cas_loss_stays_stale_on_followup_failure"` — **10 passed**, 284 deselected, 81 warnings.
- `uv run ruff check` on the eight changed Ledger/API/schema/Journaling product modules — passed.
- `uv run mypy` on the same eight modules — passed with no issues.
- Read-only 0025-shaped migration fixture — triggers installed, but `PRAGMA foreign_key_list(chat_messages)` was empty and the existing table had no delivery CHECK constraints, supporting P1-03.
- `rg -n "_retired|checkpoint_path|agent_checkpoints.sqlite|SqliteSaver|Command\\(resume" tests src/offerpilot` — no retired bodies or runtime checkpoint dependency; only intentional negative assertions remained.

The full long release gate was intentionally not run.

## Final readiness

**Not ready.** The latest fixes are meaningful and close P1-01/P1-02, P2-01..P2-05, and P3-01. They do not yet close the upgrade-schema parity gap, all authoritative fallback delivery paths, the prebuilt Journal transaction boundary, or deleted-conversation takeover. No P0 was found, but the four open P1 findings must be resolved before Phase 3 acceptance; P2-06 and P2-07 should be resolved or explicitly accepted with owner and follow-up tests.
