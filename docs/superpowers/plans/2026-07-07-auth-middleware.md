# Auth Middleware Plan

## Goal

Add a real API auth guard for server mode deployments while preserving the public health check.

## Decisions

- `auth_enabled` turns on API protection.
- `auth_token` is a local bearer token stored in `config.json` and never returned directly by settings.
- API requests can authenticate with `Authorization: Bearer <token>` or `X-OfferPilot-Token`.
- `/api/health` remains public for probes.
- If auth is enabled without a token, API routes return a clear misconfiguration error.

## Acceptance

- Protected API routes reject missing or invalid tokens.
- Protected API routes accept valid bearer and OfferPilot token headers.
- Settings reports `has_auth_token` without exposing the token.
- CLI can set the token with `oc config --auth-token`.
