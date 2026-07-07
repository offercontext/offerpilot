# LiteLLM Provider Routing Plan

## Goal

Route all AI chat completions through LiteLLM while preserving existing single-provider config compatibility.

## Sequence

1. Add failing tests for LiteLLM completion calls and provider profile serialization.
2. Add provider profile config primitives with legacy config fallback.
3. Replace hand-written provider branching in `ConfiguredAIClient` with LiteLLM completion.
4. Expose provider profiles through settings without leaking API keys.
5. Update dependencies and run full backend/frontend verification.

## Out Of Scope

- LiteLLM proxy process management.
- Cost dashboards and observability callbacks.
- Frontend multi-profile CRUD beyond current settings compatibility.
