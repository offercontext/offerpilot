# OfferPilot Write Operation Ledger Phase 3 Code Review

## Readiness decision

**Not ready for release.** No P0 finding was identified, but the review found five P1 findings affecting delivery correctness, upgrade integrity, or the required fencing contract. The P1 items should be corrected and covered by regression tests before accepting Phase 3. P2 findings below also leave important mechanical and security guarantees unproven.

## Reviewed scope and method

- Fixed baseline: `5e560580e86da7d1eb272e0df9d3d13304717499`.
- Implementation HEAD: `3b9e964ddf917cf79859fb31161744b84985b3db`.
- Working tree review also includes the uncommitted `tests/test_ai_agent.py` change present at review time: eight old persistent-checkpoint tests were renamed to `_retired_*` and their skip decorators were removed. No product source was changed by this review.
- Compared implementation and tests with `docs/superpowers/specs/2026-08-19-write-operation-ledger-design.md` and `docs/superpowers/plans/2026-08-19-write-operation-ledger.md`.
- Read the Ledger coordinator/repository, Chat repository, domain repository bindings, database schema/migration, API and SSE confirmation paths, Agent runner, tool pipeline, models, and targeted tests. Used `rg`/line-by-line source inspection and targeted read-only verification; the full long release gate was not run.

Severity means: P1 blocks release because the behavior can violate a required Phase 3 guarantee; P2 is a material integrity, security, contract, or acceptance gap; P3 is cleanup/hardening or lower-risk evidence.

## Findings

### P1-01 — Delivery heartbeat has a hard 120-second stop even when the owner is healthy

Evidence: `src/offerpilot/ai/write_operations.py:103-131` sets `self._deadline = monotonic() + DELIVERY_OWNER_LEASE_SECONDS` once and exits the heartbeat loop at line 126 when that deadline is reached. Successful CAS heartbeats at line 129 do not extend this local deadline.

The design requires the scoped heartbeat to cover the entire continuation, Bundle projection, and delivery-transaction retry window, stopping only after delivery completes/fails, fencing, or explicit abandonment (spec lines 329-344). A valid continuation containing multiple Provider/read-tool steps can exceed 120 seconds; the owner then stops renewing despite successful renewals, loses its fence, and can be taken over while its continuation is still active. This can turn an otherwise valid continuation into fallback and can race late Bundle delivery. Remove the fixed monotonic cutoff and stop only on the specified lifecycle/fence conditions; add a long-continuation heartbeat test.

### P1-02 — Concurrent first-use Ledger-key creation can overwrite a key after the lock is released

Evidence: `src/offerpilot/ai/write_operations.py:187-224` checks `key_path.exists()` and counts existing operations before acquiring the lock (lines 192-196), then, after acquiring the O_EXCL lock, unconditionally generates and replaces the key at lines 209-221. There is no second `key_path.exists()`/operation-count check after lock acquisition.

Two first requests can both observe “no key/no operations.” If the second request reaches `os.open()` after the first request has completed its `os.replace()` and removed the lock, it acquires the lock and replaces the first key. The two processes can then hold different HMAC key domains while writing the same Ledger, making fingerprints and replay verification fail closed unpredictably and invalidating the key-file continuity guarantee. Recheck the key and operation state while holding the creation lock (or use an equivalent one-writer protocol) and test the race explicitly; the specification calls out HMAC key create/race behavior (spec lines 1075-1076).

### P1-03 — The 0025 upgrade path does not install the required ChatMessage constraints/FK

Evidence: `src/offerpilot/db.py:47-67` calls `Base.metadata.create_all(engine)` and then `_ensure_write_operation_ledger_schema()`. The Phase 3 migration at `src/offerpilot/db.py:1208-1220` only adds four columns and the partial unique index for an existing `chat_messages` table. It does not rebuild/alter that table to add the model-defined delivery-group and delivery-shape CHECK constraints or the `write_operations` foreign key shown in `src/offerpilot/models.py:1427-1464`. The cross-row triggers added at `src/offerpilot/db.py:1370-1455` validate operation-bound inserts/updates, but do not retrofit the table-level constraints or FK for existing 0025 databases.

The design explicitly requires fresh and 0025 upgrade support, null backfill, ChatMessage kind/role/tool-call CHECKs, cross-table trigger, partial unique index, and FK/integrity coverage (spec lines 1008-1019 and 1061-1074). A fresh database gets model metadata, while an existing 0025 database can retain a weaker schema. This makes integrity behavior deployment-dependent and fails the required migration gate. Add a safe table rebuild/backfill (or equivalent SQLite migration) and test fresh/upgrade/repeated initialization plus malformed legacy rows.

### P1-04 — Authoritative tool-result delivery is emitted before the delivery transaction and lacks operation identity

Evidence: `src/offerpilot/ai/agent.py:771-786` emits `tool_result` immediately, and `src/offerpilot/ai/agent.py:716-721` calls `_emit_tool_result(...)` before `confirmation_result_sink(...)`. The SSE confirmation path wires that sink only as a later callback in `src/offerpilot/api.py:6872-6903`; the delivery transaction is performed by `_persist_confirmation_continuation()` at `src/offerpilot/api.py:10271-10300`, with its calls in the stream path at `src/offerpilot/api.py:7147-7205`. The payload passed to `_emit_event("tool_result", ...)` at line 786 is produced without adding the operation id.

Thus a client can receive a terminal-looking tool result before the operation-bound origin message, continuation/fallback, Pending transition, and delivery CAS are durable. A disconnect or delivery failure leaves a client-visible success that is not the durable response, and the client cannot correlate that event to the Ledger operation. The design permits only non-authoritative progress/token deltas before delivery; authoritative final/tool/chained-Pending events must be buffered until commit and carry the operation identity (spec lines 459-464 and 787-794, and API/SSE requirements in §19). Buffer `tool_result`/final/chained-Pending events with the Bundle, release them after a successful delivery transaction, and attach the same operation id on sync and SSE paths. Add response-loss, delivery-fence-loss, and event-order tests.

### P1-05 — The Ledger path performs required Journal/render/projector work after terminal commit

Evidence: `src/offerpilot/ai/write_operations.py:977-1002` renders the compatibility result and transport payload before setting terminal state and committing. After the coordinator returns, `src/offerpilot/ai/tool_runtime/pipeline.py:172-187` calls `project_tool_started()` and `project_tool_terminal()`; line 185 calls `render_compatibility()` again. The confirmation runner also recomputes the result at `src/offerpilot/ai/agent.py:690-696`, and `_emit_tool_result()` reprojects transport at `src/offerpilot/ai/agent.py:778-786`.

Phase 3 requires a prepared `tool.started` draft inserted through the same Session/SAVEPOINT before executor/terminal commit, with the terminal Journal event remaining post-commit and fail-open; it also forbids a terminal commit followed by a second renderer/projector path (spec lines 613-655 and 1049-1054). The current path can commit the domain and Ledger without `tool.started`, and any post-commit renderer/projector exception or drift cannot roll back the already committed operation. Move the prepared started projection into the coordinator transaction and make all response/replay paths consume the persisted `visible_result`/`transport_json` rather than recomputing them. Add Journal SAVEPOINT rollback and replay-no-render tests.

## P2 findings

### P2-01 — `ChatRepository.bind()` is not actually honored by operation helpers

Evidence: `src/offerpilot/repositories/chat.py:32-45` stores a bound Session and returns a bound repository, but operation proposal/confirmation/delivery helpers open `self._session_factory()` directly and commit themselves, for example `persist_pending_action` at lines 261-312, `resolve_pending_confirmation` at lines 401-470, and `persist_confirmation_continuation` at lines 565-736.

The design requires the complete ChatRepository operation surface to use the Coordinator's external Session and never commit/rollback/start another transaction in bound mode (spec lines 481-518). Although the current public helper calls are internally transactional, the advertised `bind()` contract is a bypass: callers cannot compose Chat/Pending/operation delivery with another UoW, and the AST gate cannot prove all operation paths are Session-bound. Split public self-committing wrappers from bound core methods and add a mechanical bound-repository test.

### P2-02 — Compensation execution does not revalidate the parent terminal identity in its second transaction

Evidence: the proposal transaction validates parent role/status/conversation/undo at `src/offerpilot/ai/write_operations.py:1210-1219`. In the execution transaction, `src/offerpilot/ai/write_operations.py:1259-1271` checks only that the parent exists and has `undo_json`, then derives the input fingerprint from the current payload/undo. It does not recheck `parent.operation_role == "primary"`, `parent.status == "committed"`, `parent.conversation_id == conversation_id`, or that the parent terminal identity still matches the proposal.

The design explicitly requires execution-time revalidation of request fingerprint, parent terminal digest, undo, and mutable CAS preconditions after reloading the proposed compensation (spec lines 895-907). Add those checks before appending approved/claimed; otherwise a parent/conversation change between proposal and execution can authorize an undo against a different context or parent state. Add a two-transaction mutation/deletion/replay test.

### P2-03 — Transition persistence does not enforce the fixed lifecycle in the database

Evidence: `src/offerpilot/models.py:1691-1698` constrains only allowed state strings, `seq >= 1`, and uniqueness of `(operation_id, seq)`. There is no transition trigger or equivalent check in `src/offerpilot/db.py` for required sequence/state order. A direct write can create arbitrary gaps, duplicates of lifecycle states at new sequence numbers, or a terminal transition inconsistent with the parent Operation; the Coordinator's append order is not a database integrity guarantee.

The specification requires fixed lifecycle sequencing and tests for transition sequence/order (spec lines 1066-1069). Add a trigger/centralized guarded write and malformed-transition tests, including attempted terminal-state mutation.

### P2-04 — Primary operation identity permits an empty tool-call id

Evidence: `src/offerpilot/models.py:1492-1497` requires only `tool_call_id IS NOT NULL` for a primary operation, not a non-empty/validated id. Delivery message shape elsewhere requires `tool_call_id <> ''` (`src/offerpilot/models.py:1434-1439` and `src/offerpilot/db.py:1384-1397`). A malformed primary row can therefore satisfy the role identity check but cannot produce a valid origin delivery message, creating an integrity/delivery-unknown state rather than being rejected at insertion.

Add the same non-empty bounded identity constraint used by operation-bound messages (and validate the UUID/agent-run fields required by the model contract) and cover malformed direct inserts.

### P2-05 — Retaining dead `_retired_*` checkpoint tests is not a replacement acceptance suite

Evidence: the working-tree diff in `tests/test_ai_agent.py` renames eight skipped persistent-checkpoint tests to `_retired_*` and removes the skip decorators. Their bodies still reference `checkpoint_path` and `agent_checkpoints.sqlite` (for example the renamed tests around lines 896-1137, 1399-1742, and 2572 onward). The leading underscore prevents pytest collection, so these are neither active coverage nor a clean removal of the retired contract.

Delete these obsolete bodies or replace each with Ledger-first assertions for the corresponding race, response-loss, and at-most-once scenarios. Keeping them creates stale checkpoint references that can trip mechanical scans and makes reviewers mistake dead code for Phase 3 coverage. This is specifically a release-hygiene issue in the parent’s uncommitted diff; it is not a product runtime finding.

## P3 findings

### P3-01 — Raw delivery owner token is only partially protected from generic serialization

Evidence: `DeliveryOwnership` is a normal dataclass with `raw_token: bytes` at `src/offerpilot/ai/write_operations.py:84-100`. `_Transient` blocks pickle/state hooks at lines 84-92 and `repr=False` hides the field from repr, but generic dataclass conversion such as `dataclasses.asdict()` still returns `raw_token`; no redacted export boundary is provided.

The specification forbids the raw token in State/checkpoint/log/Journal/HTTP/SSE and calls for negative scanning (spec lines 322-328 and 1052-1057). Keep the owner object confined to the delivery module and add an explicit fingerprint-only serializer plus a negative serialization test.

## Coverage and verification gaps

The Ledger-specific unit file currently has only four test functions (`tests/test_write_operations.py:44-99`), and the checkpoint replacement file contains only three static tests (`tests/tool_pipeline/test_checkpoint.py:9-24`). The reviewed suite does not establish the required matrix for:

- fresh/0025-upgrade/repeated migration and integrity backfill;
- first-use key creation race and permission/missing-key failures;
- all 12 typed, 3 legacy, and 4 compensation golden contracts;
- two-connection executor winner, mutable recheck, commit-unknown, and SAVEPOINT crash points;
- active-owner heartbeat beyond 120 seconds, takeover, late Bundle fencing, and delivery CAS;
- replay with zero executor/Provider/read-tool calls and no renderer/projector regeneration;
- operation-bound message tampering/ordinal/FK/trigger checks;
- authoritative sync/SSE event ordering and operation-id correlation;
- compensation parent revalidation and undo conflict/replay.

The eight retired tests do not close these gaps because pytest no longer collects them.

## Verification performed

Targeted, read-only checks performed during this review:

- `uv run pytest tests/test_write_operations.py -q` — 7 passed, 1 warning.
- `uv run pytest tests/tool_pipeline/test_checkpoint.py -q` — 3 passed, 1 warning.
- Selected confirmation/replay tests in `tests/test_chat_api.py` — 7 passed, 287 deselected, 41 warnings.
- `uv run ruff check src/offerpilot/ai/write_operations.py src/offerpilot/repositories/chat.py src/offerpilot/db.py src/offerpilot/models.py` — passed.
- `uv run mypy src/offerpilot/ai/write_operations.py src/offerpilot/repositories/chat.py src/offerpilot/db.py src/offerpilot/models.py` — passed.
- `python -m py_compile src/offerpilot/ai/write_operations.py` — passed.
- The full `tests/test_chat_api.py -q` run was intentionally interrupted after substantial progress and is not claimed as passing. The full long release gate was not run.

Passing targeted checks do not offset the P1 contract violations above. Re-review should require the five P1 fixes, fresh migration/key/delivery/concurrency tests, and replacement of the retired checkpoint bodies before marking Phase 3 ready.
