# Application Status Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the application status lifecycle a backend-owned single source of truth shared by API, CLI, AI tools, and frontend metadata.

**Architecture:** Add a small domain module for canonical application statuses, labels, colors, and legacy aliases. Repositories normalize persisted status values, API/CLI/tool write paths validate input, and the frontend can consume `/api/application-statuses` instead of independently inventing the lifecycle.

**Tech Stack:** Python FastAPI, Typer, SQLAlchemy repositories, pytest, React TypeScript status types.

---

## Scope Boundary

This slice establishes the contract and compatibility layer. It does not redesign the full frontend navigation, rewrite the kanban UI, or migrate existing databases destructively. Legacy status strings remain readable and are normalized on writes.

## File Structure

- Create: `src/offerpilot/application_status.py`
  - Defines canonical status IDs, Chinese labels, UI colors, legacy alias mapping, `normalize_application_status`, and `application_status_options`.
- Modify: `src/offerpilot/repositories/applications.py`
  - Normalizes create/update/list status values and guarantees dashboard buckets use canonical IDs.
- Modify: `src/offerpilot/api.py`
  - Adds `GET /api/application-statuses`; validates create/update/list status inputs; returns 422 for invalid write/filter status.
- Modify: `src/offerpilot/cli.py`
  - Adds status help text from the canonical contract and reports invalid filters cleanly.
- Modify: `src/offerpilot/ai/tools.py`
  - Uses the same status contract for AI write tools.
- Modify: `web/src/types/application.ts`
  - Replaces the frontend-only lifecycle with canonical IDs and labels.
- Tests:
  - Modify: `tests/test_applications_api.py`
  - Modify: `tests/test_cli.py`
  - Modify: `tests/test_ai_tools.py`
  - Create: `tests/test_application_status.py`

## Task 1: Domain Status Contract

**Files:**
- Create: `src/offerpilot/application_status.py`
- Create: `tests/test_application_status.py`

- [ ] **Step 1: Write failing status contract tests**

Add tests asserting canonical IDs, legacy alias normalization, and invalid status rejection.

- [ ] **Step 2: Run red test**

Run:

```powershell
uv run pytest tests/test_application_status.py -q
```

Expected: fails because `offerpilot.application_status` does not exist.

- [ ] **Step 3: Implement status contract module**

Implement canonical statuses:

```text
pending -> 待投递
applied -> 已投递
written_test -> 笔试
interview -> 面试
offer -> Offer
closed -> 结束
```

Legacy aliases:

```text
assessment -> written_test
eliminated -> closed
rejected -> closed
```

- [ ] **Step 4: Run green test**

Run:

```powershell
uv run pytest tests/test_application_status.py -q
```

Expected: passes.

## Task 2: API And Repository Enforcement

**Files:**
- Modify: `src/offerpilot/repositories/applications.py`
- Modify: `src/offerpilot/api.py`
- Modify: `tests/test_applications_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests for:

- `GET /api/application-statuses` returns the canonical lifecycle.
- Creating with `pending` stores `pending`.
- Creating with legacy `assessment` stores `written_test`.
- Creating with invalid status returns 422.
- Filtering invalid status returns 422.

- [ ] **Step 2: Run red tests**

Run:

```powershell
uv run pytest tests/test_applications_api.py -q
```

Expected: new tests fail because endpoint/validation do not exist.

- [ ] **Step 3: Implement repository normalization**

Use `normalize_application_status` in create/update/list/dashboard paths. For filters, callers should validate before calling repository.

- [ ] **Step 4: Implement API endpoint and validation**

Add `/api/application-statuses` and validate status payload/query values before repository calls.

- [ ] **Step 5: Run green tests**

Run:

```powershell
uv run pytest tests/test_applications_api.py tests/test_application_status.py -q
```

Expected: passes.

## Task 3: CLI And AI Tool Enforcement

**Files:**
- Modify: `src/offerpilot/cli.py`
- Modify: `src/offerpilot/ai/tools.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_ai_tools.py`

- [ ] **Step 1: Write failing CLI/tool tests**

Add tests for invalid CLI status filter and AI tool legacy/invalid status behavior.

- [ ] **Step 2: Run red tests**

Run:

```powershell
uv run pytest tests/test_cli.py tests/test_ai_tools.py -q
```

Expected: new tests fail because invalid status is not rejected and legacy AI status is not normalized.

- [ ] **Step 3: Implement CLI/tool validation**

CLI `list --status` rejects invalid statuses with Typer `BadParameter`; AI tools normalize accepted legacy statuses and raise `ValueError` for invalid writes.

- [ ] **Step 4: Run green tests**

Run:

```powershell
uv run pytest tests/test_cli.py tests/test_ai_tools.py -q
```

Expected: passes.

## Task 4: Frontend Status Constants

**Files:**
- Modify: `web/src/types/application.ts`

- [ ] **Step 1: Update TypeScript lifecycle**

Use canonical status IDs and labels:

```typescript
export type ApplicationStatus =
  | 'pending'
  | 'applied'
  | 'written_test'
  | 'interview'
  | 'offer'
  | 'closed';
```

- [ ] **Step 2: Build frontend**

Run from `web/`:

```powershell
npm.cmd run build
```

Expected: TypeScript build passes. If other frontend code still references removed statuses, update those references to canonical IDs or a compatibility helper.

## Task 5: Verification And Commit

**Files:**
- All files changed in tasks 1-4.

- [ ] **Step 1: Run full verification**

Run:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

Run from `web/`:

```powershell
npm.cmd test
npm.cmd run build
```

- [ ] **Step 2: Inspect diff**

Run:

```powershell
git diff --stat
git status --short
```

- [ ] **Step 3: Stage files**

Run:

```powershell
git add src/offerpilot/application_status.py src/offerpilot/repositories/applications.py src/offerpilot/api.py src/offerpilot/cli.py src/offerpilot/ai/tools.py tests/test_application_status.py tests/test_applications_api.py tests/test_cli.py tests/test_ai_tools.py web/src/types/application.ts docs/superpowers/plans/2026-07-07-application-status-contract.md
```

- [ ] **Step 4: Commit**

Run:

```powershell
git commit -m "feat: AI centralize application status contract"
```
