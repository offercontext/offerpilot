# Startup Smoke Plan

## Goal

Make the CLI startup path respect persisted runtime configuration so local and Docker startup can be smoke-tested without opening a long-running server.

## Sequence

1. Add a failing CLI smoke test for configured `local_port`.
2. Update `oc start` to default to the configured port when `--port` is omitted.
3. Preserve explicit `--port` override behavior.
4. Run full verification and commit.

## Out Of Scope

- Running Docker inside unit tests.
- Browser-driven smoke tests.
- End-to-end AI provider calls.
