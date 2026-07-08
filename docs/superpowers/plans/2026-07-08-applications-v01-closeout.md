# Applications V0.1 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the application pipeline v0.1 P0 gaps and add the basic application list view inside the pipeline module.

**Architecture:** Keep `applications` as the pipeline source of truth. Add lifecycle fields to the model/repository/API and expose them through existing application services, then build list/board UI on the same `Application` type and `['applications']` query cache.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite reset/migration helpers, pytest, React, Ant Design, React Query, Vitest, dnd-kit.

---

### Task 1: Backend Lifecycle Contract

**Files:**
- Modify: `src/offerpilot/models.py`
- Modify: `src/offerpilot/db.py`
- Modify: `src/offerpilot/repositories/applications.py`
- Modify: `src/offerpilot/schemas.py`
- Modify: `src/offerpilot/api.py`
- Test: `tests/test_applications_api.py`
- Test: `tests/test_applications_repository.py`
- Test: `tests/test_schema_compatibility.py`

- [ ] Write failing API/repository/schema tests for soft delete filtering, deleted get/update returning 404, closed status requiring `closed_reason`, and first status timestamps being set once.
- [ ] Run targeted pytest and verify the new tests fail for missing fields/behavior.
- [ ] Add `closed_reason`, `closed_at`, `deleted_at`, and first-entered status timestamp columns to `Application`; update local reset/ensure-column logic.
- [ ] Update repository create/list/get/update/delete so default reads exclude soft-deleted applications, delete writes `deleted_at`, closed status validates reason, and first-entered timestamps are only set the first time a status is reached.
- [ ] Update API payload parsing and `ApplicationOut` so frontend/Agent consumers receive the new fields.
- [ ] Run targeted pytest until green.

### Task 2: Frontend Types And Shared Helpers

**Files:**
- Modify: `web/src/types/application.ts`
- Modify: `web/src/services/applications.ts`
- Create or modify: `web/src/components/KanbanBoard/applicationLifecycle.ts`
- Test: `web/src/components/KanbanBoard/applicationLifecycle.test.ts`
- Test: `web/src/layout/CommandPalette.test.ts`

- [ ] Write failing Vitest tests for closed reason validation helper, next-event derivation, list filtering/sorting, and soft-deleted command search exclusion.
- [ ] Run targeted Vitest and verify failures.
- [ ] Add lifecycle fields to frontend `Application` / `ApplicationInput`.
- [ ] Add focused helpers for application matching, sorting, next-event display, and status-change payload construction.
- [ ] Run targeted Vitest until green.

### Task 3: Board Status Confirmation

**Files:**
- Modify: `web/src/components/KanbanBoard/index.tsx`
- Modify: `web/src/components/KanbanBoard/KanbanCard.tsx`
- Modify: `web/src/components/KanbanBoard/KanbanBoard.module.css`
- Test: helper tests from Task 2 cover business rules; browser smoke covers dnd/modal behavior.

- [ ] Replace immediate drag status mutation with a confirmation modal.
- [ ] Show source status, target status, whether a first-entered timestamp will be set, and a required close reason when moving to `closed`.
- [ ] Use the same confirmation path for the card status select.
- [ ] Keep cancel as a no-op so the card stays in the original column.
- [ ] Keep delete as soft-delete via existing `DELETE /api/applications/{id}` endpoint and invalidate application/event-dependent views.

### Task 4: Application List View

**Files:**
- Modify: `web/src/layout/navigation.ts`
- Modify: `web/src/layout/AppShell.tsx`
- Create: `web/src/components/ApplicationListView.tsx`
- Create: `web/src/components/ApplicationListView.module.css`
- Test: `web/src/components/ApplicationListView.test.ts`

- [ ] Add `applications-list` view under the pipeline module as the sibling tab to `board`.
- [ ] Render company, position, status, priority/source, next event, and updated time.
- [ ] Support keyword search, status filter, sortable updated/applied date, and click-to-detail/edit.
- [ ] Ensure soft-deleted applications do not appear because the API list excludes them.
- [ ] Run targeted Vitest until green.

### Task 5: Cmd+K And Integration Verification

**Files:**
- Modify: `web/src/layout/CommandPalette.tsx`
- Modify: `web/src/layout/CommandPalette.test.ts`
- Modify: `web/src/layout/AppShell.tsx`

- [ ] Add direct commands for application list, board, due events/calendar, and stale follow-up actions.
- [ ] Keep application search results scoped to non-deleted applications.
- [ ] Ensure command runs open detail or navigate to the correct pipeline view.
- [ ] Run targeted Vitest until green.

### Task 6: Full Validation And Review

**Files:**
- No planned source edits unless validation finds a defect.

- [ ] Run backend targeted tests, then full `uv run pytest`.
- [ ] Run `uv run ruff check .` and `uv run mypy src`.
- [ ] Run `cd web && npm test -- --run` and `cd web && npm run build`.
- [ ] Start the app and smoke with the built-in Codex browser: create/edit application, drag with confirm, close with reason, add event, see list/board/calendar/Cmd+K behavior, soft-delete and confirm hidden.
- [ ] Dispatch a code-review subagent and fix actionable findings.
