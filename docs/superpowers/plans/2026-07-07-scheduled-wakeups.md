# Scheduled Wakeups Plan

## Goal

Create a durable local wakeup queue that can support future assistant follow-ups and scheduled agent runs.

## Decisions

- Store wakeups in SQLite with `kind`, `due_at`, `payload_json`, `status`, and `dispatched_at`.
- Keep dispatch explicit for v0.1: API and CLI can mark due wakeups as dispatched.
- Use JSON payloads so future workflows can attach application ids, prompt context, or workflow ids without a schema migration.
- Do not add a background scheduler yet; this keeps local-first behavior predictable.

## Acceptance

- `/api/wakeups` can create and list wakeups.
- `/api/wakeups/dispatch-due` marks only due pending wakeups as dispatched.
- `oc wakeup add/list/dispatch-due` mirrors the backend capability.
- Wakeups do not dispatch twice.
