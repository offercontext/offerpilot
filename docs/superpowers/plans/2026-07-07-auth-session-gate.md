# Auth Session Gate Plan

## Goal

Provide a browser entry point for workspaces protected by the API auth middleware.

## Decisions

- `/api/auth/status` is public and reports whether the current request is authenticated.
- Disabled auth is treated as authenticated so local mode goes straight into the app.
- `AuthGate` blocks the app shell only when auth is enabled and the stored token is invalid or missing.
- The token prompt stores the token with the shared auth token helper.

## Acceptance

- Auth status is reachable without a token.
- Auth status reports authenticated when a valid token is sent.
- The app shell is wrapped in `AuthGate`.
- Frontend tests and production build pass.
