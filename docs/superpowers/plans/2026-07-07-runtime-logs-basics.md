# Runtime And Logs Basics Plan

## Goal

Add the v0.1 platform basics for runtime mode, auth switch, log level, and a local diagnostics log endpoint.

## Sequence

1. Add failing tests for config defaults and settings update.
2. Add failing tests for reading recent diagnostics logs.
3. Add config fields and API payload support.
4. Add a small diagnostics log reader/writer.
5. Add CLI config flags for runtime and log level.
6. Run full verification and commit.

## Out Of Scope

- Full authentication middleware.
- Log streaming UI.
- Structured observability dashboards.
