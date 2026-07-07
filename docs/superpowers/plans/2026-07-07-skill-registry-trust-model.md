# Skill Registry Trust Model Plan

## Goal

Establish a first safe contract for user-installable skill packages without executing third-party code.

## Decisions

- A skill package is metadata in `config.json`: id, label, version, source, trusted, enabled.
- New packages are registered as untrusted and disabled by default.
- A package is considered loaded only when it is both trusted and enabled.
- Enabling an untrusted package fails fast.
- API and CLI share the same registry helpers.

## Acceptance

- `/api/skills` lists registered packages and loaded ids.
- `/api/skills` can register packages without auto-trusting them.
- `/api/skills/{id}` enforces trust before enable.
- `oc skill add/list/trust/enable/disable` manages the same registry.
