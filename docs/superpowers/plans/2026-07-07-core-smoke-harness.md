# Core Smoke Harness Plan

## Goal

Add a deterministic smoke harness that verifies the v0.1 core loop without requiring a real model provider or a long-running server.

## Sequence

1. Add failing tests for the smoke harness and CLI command.
2. Implement an in-process smoke runner using the real FastAPI app and a scripted chat model.
3. Wire `oc smoke` to run the harness and print the checked steps.
4. Run full verification and commit.

## Out Of Scope

- Browser automation screenshots.
- Docker build/run execution in tests.
- External model provider calls.
