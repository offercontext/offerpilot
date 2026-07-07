# Skill Manifest Provenance Plan

## Goal

Strengthen the skill registry with manifest validation and provenance metadata before any execution sandbox is introduced.

## Decisions

- Accept either legacy top-level skill metadata or a `manifest` object.
- Validate required manifest id and reject mismatched top-level ids.
- Store description, entrypoint, inferred source type, and a SHA-256 digest of canonical manifest JSON.
- Keep registered packages untrusted and disabled by default.
- Do not execute skill code in this slice.

## Acceptance

- `/api/skills` can register a manifest and returns provenance fields.
- Invalid manifests fail with clear 400 errors.
- `oc skill add --manifest path/to/skill.json` registers the same metadata.
- Existing trust-before-enable behavior remains intact.
