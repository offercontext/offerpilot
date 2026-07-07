# Persist Pending Actions Plan

## Goal

Persist human-in-the-loop pending actions on the conversation record so the UI can recover confirmation state after reloads and future agent runners can build on an explicit checkpoint.

## Sequence

1. Add failing API tests for pending action recovery and clearing.
2. Add additive conversation columns and repository helpers.
3. Store pending actions when the agent pauses for confirmation.
4. Read and clear persisted pending actions on confirmation.
5. Expose pending action metadata through conversation payloads.
6. Run full verification and commit.

## Out Of Scope

- Full LangGraph checkpoint migration.
- Multi-branch / time-travel execution.
- Scheduled wakeups.
