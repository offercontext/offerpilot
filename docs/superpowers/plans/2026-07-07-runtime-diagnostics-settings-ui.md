# Runtime Diagnostics Settings UI Plan

## Goal

Expose runtime configuration and recent diagnostics logs in the settings module.

## Design Notes

- Keep the settings page operational and scan-friendly.
- Use existing Ant Design components and OfferPilot theme variables.
- Avoid a marketing layout; this is a repeated-use settings surface.
- Keep controls at stable sizes and use icon buttons for refresh.

## Acceptance

- Settings shows runtime mode, log level, auth state, and API key state.
- Settings fetches `/api/logs` and renders recent entries.
- The logs panel has loading and empty states.
- Frontend tests and production build pass.
