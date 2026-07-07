# Auth Client Token Plan

## Goal

Make browser API clients compatible with the new auth middleware.

## Decisions

- Store the browser token under `offerpilot.auth_token`.
- Send the token as `X-OfferPilot-Token` on every frontend API client.
- Keep all axios client creation behind one shared helper.
- Keep token storage helpers pure and unit-tested.

## Acceptance

- Token helpers trim, store, clear, and produce request headers.
- All frontend service clients use the shared authenticated axios helper.
- Frontend tests and production build pass.
