# Module IA Shell Plan

## Goal

Align the web shell with the wiki's product modules while keeping the current implementation shippable and small.

## Sequence

1. Add a pure navigation contract for top modules, default views, and in-module tabs.
2. Cover the contract with Vitest before wiring UI.
3. Move the sidebar from page-level items to module-level items.
4. Add module tabs in the app content area for secondary views.
5. Add a first-class settings view that can open AI runtime settings.
6. Run backend and frontend verification, then commit.

## Out Of Scope

- Persistent Pilot right rail.
- Full visual theme overhaul.
- New backend data models for skills, RAG, or agent state.
