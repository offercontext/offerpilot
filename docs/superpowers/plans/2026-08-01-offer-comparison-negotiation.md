# Offer Comparison and Negotiation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Extend the existing Offer center with auditable comparison dimensions and a single-Offer negotiation-preparation flow while preserving user decision authority, strict evidence gating, and the existing Chat context contract.

**Architecture:** Add a small Offer-domain persistence layer for workspace comparison dimensions, per-Offer values, immutable negotiation Attempts/Proposals, and one-confirmation Briefs. The Offer center and Pilot call the same API and repository paths; Pilot only supplies an explicitly selected Offer context and never owns a second state machine. Existing Offer CRUD and comparison remain the source of current facts; historical Proposal/Brief rows retain ordinary IDs and frozen snapshots so Offer edits or deletion cannot rewrite history.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, Pydantic, existing provider client/JSON-contract helpers, React, TypeScript, Ant Design, TanStack Query, Vitest, pytest, PowerShell harnesses.

---

## Scope and fixed contracts

The implementation starts from main@9ee97a8 in D:\Users\yuqi.chen\offerpilot\.worktrees\feat-20260801-offer-negotiation. The Application Journey task is abandoned and must not be edited. The root worktree's uncommitted tests/test_smoke.py is outside this task and must not be touched.

The following contracts are fixed before implementation:

1. A single visible Offer can start negotiation preparation without comparison. Multiple comparison requires at least two distinct visible IDs and preserves the submitted order.
2. Comparison has facts, user notes, custom dimensions, values, and missing-information markers only. There is no score, ranking, weight, average, best/optimal label, positive/negative color, or accept/decline recommendation.
3. Current comparison values may be edited or archived. Confirmed Briefs and Proposals retain frozen source data and ordinary offer_id/application_id integers; current Offer deletion never cascades into historical rows.
4. Generation input is exactly the selected Offer facts, selected active comparison dimension values, and the user's current goal/concerns/scenario. It excludes full Chat history, other Offers, external sources, URLs, provider internals, and unrelated application data.
5. The Proposal JSON has exactly proposal_status, communication_goals, clarification_questions, talking_points, and preparation_checks. Normal items have exactly id, text, rationale, and evidence_refs; each evidence reference has exactly source, path, and excerpt. Evidence sources are offer_snapshot or user_brief.
6. 422 creates no Attempt and clears a definite client draft; 404 means the current Offer is unavailable while historical reads remain possible; 409 means snapshot/idempotency/source conflict; 202 and 502 unknown results retain Attempt, key, and frozen input; deterministic contract failure becomes the persisted safe-empty Proposal after at most one permitted repair.
7. Only explicit user confirmation creates one Brief. Confirmation is unique by Proposal, atomic, replayable, and never creates a Chat message, reminder, material, question, knowledge asset, application mutation, or external action.
8. Chat remains context_type=application plus context_ref=<application_id> for an associated Offer, or workspace context otherwise. No offer_id field is added to conversation persistence.

## File map

Create or modify only these functional areas unless a focused test proves an existing shared helper must be extended:

- Backend models and migration: src/offerpilot/models.py, src/offerpilot/db.py.
- Backend schemas/routes/repositories: src/offerpilot/schemas.py, src/offerpilot/api.py, src/offerpilot/repositories/offer_comparison.py, src/offerpilot/repositories/offer_negotiation.py.
- AI contract: src/offerpilot/ai/offer_negotiation.py and the smallest existing JSON-contract/provider helper required for shared parsing.
- Backend tests: tests/test_offer_comparison_dimensions.py, tests/test_offer_negotiation_api.py, tests/test_offer_negotiation_repository.py, tests/test_offer_negotiation_ai.py, tests/test_offer_negotiation_migration.py.
- Frontend contract/service: web/src/types/offer.ts, web/src/services/offers.ts.
- Frontend Offer center: web/src/components/OfferCenterView.tsx, web/src/components/OfferCard.tsx, web/src/components/OfferCompareDrawer.tsx, new web/src/components/OfferNegotiationDrawer.tsx.
- Frontend Pilot integration: existing Pilot attachment/context files under web/src/features/pilot/, web/src/components/ChatPanel/, and web/src/layout/AppShell.tsx; do not add a Chat database field.
- Isolated verification: scripts/offer-negotiation-real-ai-browser-harness.ps1, tests/test_offer_negotiation_browser_harness.py, and existing smoke/verify entry points only where a task explicitly adds scoped coverage.

Every task below is test-first: write the named failing tests, run them to establish the failure, implement the smallest change, rerun the focused command, and make the listed small commit. Do not batch unrelated tasks into one commit.

## Task 1: Establish migration and source-of-truth safety

**Files:**
- Create: tests/test_offer_negotiation_migration.py
- Modify: src/offerpilot/models.py, src/offerpilot/db.py

- [ ] Step 1: Add migration contract tests before model changes. Cover a fresh database and a real pre-feature SQLite schema with the current Offer table plus no negotiation tables. Assert startup creates migration 0017_offer_comparison_negotiation, all four new tables and unique indexes exist, and running init_database twice does not duplicate or alter rows. Insert an Offer and verify its current fields are byte-equivalent after migration.
- [ ] Step 2: Run uv run pytest tests/test_offer_negotiation_migration.py -q; it must fail because the feature tables and migration marker do not exist.
- [ ] Step 3: Add OfferComparisonDimension, OfferComparisonValue, OfferNegotiationProposal, and OfferNegotiationBrief. Use these exact fields:
  - Dimension: id, nonblank label, nullable archived_at, created_at, updated_at.
  - Value: id, offer_id, dimension_id, value_text, created_at, updated_at, unique (offer_id, dimension_id).
  - Proposal: ordinary immutable offer_id and nullable application_id, ASCII idempotency_key, attempt_status, source_fingerprint, input_snapshot_json, proposal_json, proposal_hash, source_states_json, nullable lease_token, lease_expires_at, revision, invalidation_reason, created_at, ready_at; unique (offer_id, idempotency_key).
  - Brief: proposal_id unique, ordinary immutable offer_id, nullable origin_application_id, selected_blocks_json, edited_content_json, confirmed_at.
  Current-value rows may be cleaned with an Offer, but no historical table may use an FK that cascades or blocks Offer deletion.
- [ ] Step 4: Add an explicit 0017_offer_comparison_negotiation migration helper after Base.metadata.create_all. It must create missing tables/indexes for an old database, use INSERT OR IGNORE for the migration record, and leave existing Offer bytes and migration records unchanged. Run the fresh/old/repeated-startup tests until all pass.
- [ ] Step 5: Commit:
~~~powershell
git add src/offerpilot/models.py src/offerpilot/db.py tests/test_offer_negotiation_migration.py
git commit -m "feat: AI add offer negotiation schema"
~~~

## Task 2: Implement custom comparison dimensions and values

**Files:**
- Create: src/offerpilot/repositories/offer_comparison.py, tests/test_offer_comparison_dimensions.py
- Modify: src/offerpilot/schemas.py, src/offerpilot/api.py, web/src/types/offer.ts, web/src/services/offers.ts

- [ ] Step 1: Add failing repository/API tests for nonblank labels, archive behavior, active-only listing, old archived values remaining readable, one value per Offer/dimension, exact user text preservation, invisible/soft-deleted Offer rejection, and stable Chinese 422 for blank labels/values. Assert no score/rating fields exist.
- [ ] Step 2: Run uv run pytest tests/test_offer_comparison_dimensions.py -q; it must fail before the endpoints/repository exist.
- [ ] Step 3: Add repository functions for visible Offer lookup, active dimension listing, value upsert, archive, and current comparison payload assembly. Add these exact routes:
  - GET /api/offers/comparison-dimensions
  - POST /api/offers/comparison-dimensions with {label}
  - PATCH /api/offers/comparison-dimensions/{dimension_id} with {label?, archived?}
  - GET /api/offers/{offer_id}/comparison-values
  - PUT /api/offers/{offer_id}/comparison-values/{dimension_id} with {value_text}
  Validate positive IDs, visible Offer ownership, nonblank UTF-8 text, and reject score/rating fields.
- [ ] Step 4: Add typed OfferComparisonDimension, OfferComparisonValue, request/response types and typed service functions in web/src/types/offer.ts and web/src/services/offers.ts. Do not add an offer_id Chat context field.
- [ ] Step 5: Run uv run pytest tests/test_offer_comparison_dimensions.py -q; run relevant web service tests; commit:
~~~powershell
git add src/offerpilot/repositories/offer_comparison.py src/offerpilot/schemas.py src/offerpilot/api.py tests/test_offer_comparison_dimensions.py web/src/types/offer.ts web/src/services/offers.ts
git commit -m "feat: AI add offer comparison dimensions"
~~~

## Task 3: Harden the existing multi-Offer comparison contract

**Files:**
- Modify: src/offerpilot/api.py, src/offerpilot/repositories/offers.py, web/src/components/OfferCenterView.tsx, web/src/components/OfferCard.tsx, web/src/components/OfferCompareDrawer.tsx
- Test: tests/test_offers_api.py, web/src/components/OfferCenterView.test.tsx, new web/src/components/OfferCompareDrawer.test.tsx

- [ ] Step 1: Add failing tests for duplicate IDs being removed before the minimum-two check, missing/invisible IDs returning stable errors, and two visible distinct IDs preserving request order. Mounted UI tests must reject score/rank/weight/average/best/recommend/accept/decline wording and show blank values as 尚未填写.
- [ ] Step 2: Run uv run pytest tests/test_offers_api.py -q and npm.cmd test -- --run src/components/OfferCenterView.test.tsx src/components/OfferCompareDrawer.test.tsx from web.
- [ ] Step 3: Keep comparison in Offer center only. Pass active dimension/value rows into the drawer without sorting user-selected Offer columns. Add explicit “用此 Offer 准备谈薪” callbacks carrying the exact Offer ID; do not infer an Offer from column position after rerender.
- [ ] Step 4: Rerun both focused commands and commit:
~~~powershell
git add src/offerpilot/api.py src/offerpilot/repositories/offers.py web/src/components/OfferCenterView.tsx web/src/components/OfferCard.tsx web/src/components/OfferCompareDrawer.tsx tests/test_offers_api.py web/src/components/OfferCenterView.test.tsx web/src/components/OfferCompareDrawer.test.tsx
git commit -m "feat: AI harden offer comparison"
~~~

## Task 4: Build the strict negotiation Proposal contract

**Files:**
- Create: src/offerpilot/ai/offer_negotiation.py, src/offerpilot/repositories/offer_negotiation.py, tests/test_offer_negotiation_ai.py, tests/test_offer_negotiation_repository.py
- Modify: src/offerpilot/api.py, src/offerpilot/schemas.py

- [ ] Step 1: Add failing AI/repository tests for duplicate JSON keys, fenced JSON, non-object roots, missing/extra fields, wrong types, blank id/text/rationale/excerpt, non-finite values, concrete array limits, duplicate item IDs across all arrays, invalid source/path/excerpt, and forbidden decision/law/market/company-policy assertions. Also cover valid normal, fixed safe_empty with four empty arrays, no-evidence no-provider behavior, one repair for pure structure, terminal 502 for semantic evidence/limit/decision errors, provider/network unknown retaining key, and 422 creating no Attempt.
- [ ] Step 2: Run uv run pytest tests/test_offer_negotiation_ai.py tests/test_offer_negotiation_repository.py -q; expected failure is the absent parser/validator/repository behavior.
- [ ] Step 3: Define parse_offer_negotiation_json, validate_offer_negotiation, classify_offer_negotiation_failure, and a server-generated SAFE_EMPTY_OFFER_NEGOTIATION. Parse with duplicate-key rejection, reject fenced text/non-finite values, enforce exact fields, and codify these concrete limits: at most 8 items in each of the four arrays, at most 4 evidence_refs per item, at most 64 Unicode characters for id, at most 600 characters for text/rationale, at most 400 characters for excerpt, and at most 8 active comparison dimensions in one snapshot. Validate each reference against the frozen canonical snapshot. Version fixed context-free questions; factual questions require evidence. Only pure structure failures may trigger repair; fake source/path/excerpt, over-limit, duplicate semantic IDs, and forbidden decision language are terminal.
- [ ] Step 4: Implement prepare_or_replay, claim_generation, mark_provider_unknown, complete_ready, and invalidate. First transaction inserts the row with generating, revision 1, random lease token and unexpired lease before Provider. Same key/different fingerprint is 409. Ready is immutable. Provider-unknown returns 202 while lease is live and can be claimed only after expiry. Writes match status/revision/lease token; a late owner cannot overwrite ready.
- [ ] Step 5: Add these typed routes: POST /api/offers/{offer_id}/negotiation/proposals for generation, GET /api/offers/{offer_id}/negotiation/proposals for current-Offer history, GET /api/offer-negotiation/proposals/{proposal_id} for immutable history after Offer changes, and POST /api/offer-negotiation/proposals/{proposal_id}/confirm for HITL handoff. Validate visible Offer/current input before creating an Attempt; historical reads return frozen content with source_changed after Offer edit/delete. Use distinct 201/200/202/409/422/502 envelopes and safe Chinese mapping. Diagnostics contain only category, HTTP status, timeout, elapsed time, repair count, and hashed Provider request ID.
- [ ] Step 6: Run uv run pytest tests/test_offer_negotiation_ai.py tests/test_offer_negotiation_repository.py tests/test_offer_negotiation_api.py -q; commit:
~~~powershell
git add src/offerpilot/ai/offer_negotiation.py src/offerpilot/repositories/offer_negotiation.py src/offerpilot/api.py src/offerpilot/schemas.py tests/test_offer_negotiation_ai.py tests/test_offer_negotiation_repository.py tests/test_offer_negotiation_api.py
git commit -m "feat: AI add offer negotiation proposals"
~~~

## Task 5: Add atomic HITL Brief confirmation and historical reads

**Files:**
- Modify: src/offerpilot/repositories/offer_negotiation.py, src/offerpilot/api.py, src/offerpilot/schemas.py
- Test: tests/test_offer_negotiation_api.py, tests/test_offer_negotiation_repository.py

- [ ] Step 1: Add failing tests binding Proposal, Offer, application_id, selected block IDs, edited content, and source fingerprint in one transaction. No Brief may exist before confirmation. Successful confirmation creates exactly one Brief. Concurrent two-session confirmations create one row and replay the same Brief. Changed source returns 409 with no write. Deleted Offer leaves Proposal/Brief history readable and marked changed.
- [ ] Step 2: Run uv run pytest tests/test_offer_negotiation_api.py -k "confirm or brief or source_changed" -q.
- [ ] Step 3: Implement confirm_proposal with the repository transaction pattern and UNIQUE(proposal_id). Validate selected blocks against immutable Proposal and store user edits only as derived content with Proposal evidence retained. A uniqueness hit returns the original Brief.
- [ ] Step 4: Return immutable Proposal/Brief content, source_states, source_changed, offer_id, and application_id from history. Never rewrite hashes or rebind to a new Offer. Map 404/409/422 to safe Chinese messages.
- [ ] Step 5: Run uv run pytest tests/test_offer_negotiation_api.py tests/test_offer_negotiation_repository.py -q; commit:
~~~powershell
git add src/offerpilot/repositories/offer_negotiation.py src/offerpilot/api.py src/offerpilot/schemas.py tests/test_offer_negotiation_api.py tests/test_offer_negotiation_repository.py
git commit -m "feat: AI add offer negotiation confirmation"
~~~

## Task 6: Add Offer-center single-Offer negotiation flow

**Files:**
- Create: web/src/components/OfferNegotiationDrawer.tsx, web/src/components/OfferNegotiationDrawer.test.tsx
- Modify: web/src/types/offer.ts, web/src/services/offers.ts, web/src/components/OfferCard.tsx, web/src/components/OfferCenterView.tsx

- [ ] Step 1: Add failing mounted UI tests using mocked typed services, not source-string assertions. Cover single-Offer entry, required goal/concerns/scenario, explicit generation confirmation, exact frozen-source display, editable four-block result, selection/edit/confirm, 202/502/network freezing with same-key retry, 422 draft cleanup, 409 source_changed read-only history, and zero unrelated write calls.
- [ ] Step 2: Run from web: npm.cmd test -- --run src/components/OfferNegotiationDrawer.test.tsx src/components/OfferCenterView.test.tsx; record the expected failures.
- [ ] Step 3: Add typed service functions for generation, history, retry, and Brief confirmation. Keep attempt state keyed by offerId in the durable parent/state pattern so unmount/reopen retains unknown key and frozen input. Distinguish definite failure from unknown result; render only Chinese safe messages and never raw provider/Axios/snapshot text.
- [ ] Step 4: Add the card entry and center integration. Preserve existing Offer CRUD/layout and pass exact Offer IDs from compare columns.
- [ ] Step 5: Rerun focused tests and commit:
~~~powershell
git add web/src/components/OfferNegotiationDrawer.tsx web/src/components/OfferNegotiationDrawer.test.tsx web/src/types/offer.ts web/src/services/offers.ts web/src/components/OfferCard.tsx web/src/components/OfferCenterView.tsx
git commit -m "feat: AI add offer negotiation UI"
~~~

## Task 7: Integrate explicit Offer context into Pilot

**Files:**
- Modify: existing Pilot attachment/context files under web/src/features/pilot/, web/src/components/ChatPanel/, and web/src/layout/AppShell.tsx only where the current attachment contract requires it.
- Test: new web/src/components/OfferPilotNegotiation.test.tsx, existing Pilot attachment/context tests, tests/test_chat_api.py, tests/test_chat_repository.py if backend context behavior needs a regression.

- [ ] Step 1: Add failing integration tests for no selected Offer (list and require choice), explicit selected Offer (static card only), associated context_type=application/context_ref, workspace context for unassociated Offer, no persisted offer_id payload, same service functions for Pilot/UI, and no auto-send/provider call before confirmation.
- [ ] Step 2: Run from web: npm.cmd test -- --run src/components/OfferPilotNegotiation.test.tsx src/features/pilot/PilotAttachmentContext.render.test.tsx.
- [ ] Step 3: Reuse explicit Offer attachment. Add no new Chat discriminator, API route, prompt, repository, retry state, or auto-approval path. The Pilot action opens the same drawer after explicit selection.
- [ ] Step 4: Rerun focused tests, Chat tests if changed, and commit:
~~~powershell
git add web/src/features/pilot web/src/components/ChatPanel web/src/layout/AppShell.tsx web/src/components/OfferPilotNegotiation.test.tsx tests/test_chat_api.py tests/test_chat_repository.py
git commit -m "feat: AI connect offer negotiation to Pilot"
~~~

## Task 8: Complete error handling, diagnostics, and isolated browser harness

**Files:**
- Create or modify: scripts/offer-negotiation-real-ai-browser-harness.ps1, tests/test_offer_negotiation_browser_harness.py
- Modify only scoped diagnostic/error mapping paths in src/offerpilot/api.py, src/offerpilot/ai/offer_negotiation.py, and web/src/components/OfferNegotiationDrawer.tsx.

- [ ] Step 1: Add failing harness/error tests for redacted Chinese mapping, scoped diagnostics, 422 cleanup, 404 history/source_changed, 409 freeze, 202/502 retained key, and same-key replay.
- [ ] Step 2: Implement an isolated temporary data directory and redacted config copy. Record only local browser /api requests and actual configured Provider scheme+host+port. Fail closed on any unapproved host or server egress. Never emit keys, Offer/JD/resume text, evidence excerpts, raw model output, or snapshots.
- [ ] Step 3: Add the real sequence: create two Chinese Offers; add 通勤 and 成长空间; compare in user order without ranking; select one Offer; fill Chinese goal/concerns/scenario; confirm AI; inspect evidence; edit/select blocks; confirm Brief; close/reopen history; explicitly select the same Offer in Pilot and open the same flow. Assert no application/event/resume/material/question/knowledge/reminder/Chat write beyond explicit Offer/Proposal/Brief operations.
- [ ] Step 4: Run uv run pytest tests/test_offer_negotiation_browser_harness.py -q and the Offer-specific isolated real-AI verify command; do not substitute another AI flow.
- [ ] Step 5: Commit:
~~~powershell
git add scripts/offer-negotiation-real-ai-browser-harness.ps1 tests/test_offer_negotiation_browser_harness.py src/offerpilot/api.py src/offerpilot/ai/offer_negotiation.py web/src/components/OfferNegotiationDrawer.tsx
git commit -m "test: AI verify offer negotiation boundaries"
~~~

## Task 9: Independent review and complete release gates

**Files:**
- Review all changed files.
- Create: docs/reports/2026-08-01-offer-negotiation-release-verification.md

- [ ] Step 1: From the Offer worktree root run:
~~~powershell
uv run pytest tests/test_offer_comparison_dimensions.py tests/test_offer_negotiation_migration.py tests/test_offer_negotiation_ai.py tests/test_offer_negotiation_repository.py tests/test_offer_negotiation_api.py tests/test_offer_negotiation_browser_harness.py -q
uv run ruff check src tests
uv run mypy src
Set-Location web
npm.cmd test -- --run src/components/OfferCenterView.test.tsx src/components/OfferCompareDrawer.test.tsx src/components/OfferNegotiationDrawer.test.tsx src/components/OfferPilotNegotiation.test.tsx
npm.cmd run build
Set-Location ..
git diff --check main..HEAD
~~~
Record actual exit codes and counts; a timeout is not a pass.
- [ ] Step 2: Obtain independent code review for history retention, duplicate IDs, duplicate JSON, evidence validation, lease/CAS, confirmation uniqueness, Pilot leakage, cross-domain writes, and raw-content logging. Fix P0/P1 with regression tests; name any accepted P2 in the report.
- [ ] Step 3: Run grouped backend gate rather than one timeout-prone pytest. Verify collected node-id manifest equals a disjoint group union, no node appears twice, and only the four pre-approved Windows symlink-permission skips occur with exact reasons. Run frontend full tests in stable groups, TypeScript/build, Ruff, Mypy, local smoke, local verify, and Offer-specific real-AI verify.
- [ ] Step 4: Run isolated browser flow with copied redacted config and temporary OFFERPILOT_DATA. Verify local-only browser traffic, exact Provider endpoint egress, no recruitment access, HITL confirmations, source-changed history, and zero unrelated writes. Stop services, browser targets, and proxy; remove temp data; compare the original user data directory before/after.
- [ ] Step 5: Write docs/reports/2026-08-01-offer-negotiation-release-verification.md with commit/base, commands, exit codes, counts, skips, focused/AI/browser results, cleanup comparison, review findings, and risks. Do not include secrets, Offer/JD/resume text, evidence excerpts, raw model output, or raw request IDs.
- [ ] Step 6: Scan changed files for placeholder markers, placeholder error mappings, decision language, and offer_id Chat context fields. Run git diff --check main..HEAD, confirm git status --short is empty, then separately stage and commit the report:
~~~powershell
git add docs/reports/2026-08-01-offer-negotiation-release-verification.md
git commit -m "docs: AI record offer negotiation release verification"
~~~

## Plan self-review

- [x] Single-Offer negotiation and optional multi-Offer comparison are separate.
- [x] Custom dimensions preserve user text, support archive, and never become scores.
- [x] New migration is unused 0017_offer_comparison_negotiation; fresh and real-old-database upgrades are tested.
- [x] Proposal snapshot, fingerprint, hash, idempotency, lease/CAS, unknown result, one repair, safe-empty, and source-change history are assigned to tasks.
- [x] Brief confirmation has transaction-level ownership validation and UNIQUE(proposal_id) replay.
- [x] UI and Pilot share APIs; Pilot requires explicit Offer selection and no offer_id Chat persistence.
- [x] No auto-decision, auto-send, external recruitment access, cross-domain write, or Offer-state mutation is introduced.
- [x] Browser verification is isolated, Chinese, redacted, and checks actual local/Provider boundaries.
- [x] Paths, route names, types, statuses, and error semantics are consistent with the approved design; no placeholder instruction is required.
