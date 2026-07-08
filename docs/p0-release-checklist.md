# P0 Release Checklist

Date: 2026-07-07
Branch: `codex/feat/project-adjustments-review`

This checklist is the non-Docker v0.1 release gate for the project-adjustments worktree. Docker is intentionally excluded from this local gate because the current machine does not have Docker available.

## Scope Status

| P0 area | Status | Evidence |
| --- | --- | --- |
| License and public positioning | Complete | `LICENSE` is AGPLv3; README and `CONTRIBUTING.md` state AGPLv3 contribution terms. |
| Application lifecycle contract | Complete | Backend owns `pending -> applied -> written_test -> interview -> offer -> closed`; legacy status aliases are normalized. |
| Product IA | Complete | Navigation is grouped by module-level workspace areas instead of implementation pages. |
| Pilot product surface | Complete | Desktop Pilot is a persistent rail; narrow screens retain drawer behavior. |
| Platform basics | Complete | Settings expose provider profiles, runtime mode, auth status, and diagnostics logs. |
| AI provider routing | Complete | LiteLLM backs configured provider profiles and preserves provider-specific blocks such as reasoning content. |
| HITL durability | Complete | Pending actions survive reloads via persisted conversation pending fields. |
| Schema safety | Complete | Additive startup repairs are tracked in `schema_migrations`. |
| Local release smoke | Complete | `scripts/local-smoke.ps1` and `scripts/local-smoke.sh` build the SPA, start `oc start`, check health and SPA fallback, then run `oc smoke`. `oc verify --profile local` starts a real HTTP app and exercises API/chat write confirmation over localhost. |
| Docker: deferred | Deferred | Docker build/run smoke is covered by scripts and static tests, but not executed locally because Docker is unavailable. |

## Required Non-Docker Gate

Run these before treating the branch as locally releasable:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
cd web
npm.cmd test
npm.cmd run build
cd ..
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\local-smoke.ps1
uv run oc verify --profile local --static-dir web/dist
```

When existing AI credentials are available and real provider calls are allowed, also run:

```powershell
uv run oc verify --profile real-ai --static-dir web/dist
```

On Unix-like shells:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
cd web
npm test
npm run build
cd ..
scripts/local-smoke.sh
uv run oc verify --profile local --static-dir web/dist
```

When existing AI credentials are available and real provider calls are allowed, also run:

```bash
uv run oc verify --profile real-ai --static-dir web/dist
```

## Deferred After P0

- Docker image build/run verification on a machine with Docker.
- Full LangGraph checkpoint migration beyond durable pending actions.
- Skill execution sandbox beyond trust/manifest provenance.
- Screenshot-level responsive QA for dense data views.
