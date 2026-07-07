# Pilot Rail Shell Plan

## Goal

Make Pilot a persistent assistant surface on desktop while preserving the drawer interaction on smaller screens.

## Sequence

1. Add a rail variant to the existing chat panel instead of duplicating assistant logic.
2. Dock the rail in the app shell for wide viewports.
3. Keep the existing drawer as the fallback for tablet and mobile.
4. Verify with frontend tests/build and backend checks, then commit.

## Out Of Scope

- Rewriting assistant prompts or backend tool behavior.
- New conversation persistence semantics.
- Full responsive visual audit with browser screenshots.
