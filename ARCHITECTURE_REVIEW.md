# OfferPilot Architecture Review

Date: 2026-07-04
Branch: `codex/feat-architecture-review`
Baseline: `origin/main` at `6f464fc`

## First Principles

OfferPilot is strongest when it remains a local-first, single-binary job-search
workbench. The architecture should optimize for four properties:

1. Low setup cost: one command should start a useful local product.
2. Clear change boundaries: adding a workflow should not require touching every
   entry point.
3. Trustworthy local data: persistence, migrations, and AI write actions need
   predictable failure modes.
4. Fast feedback: backend, frontend, and packaging should be easy to test in
   isolation.

The current design fits the product stage: Go + SQLite + chi + Cobra + Vite is a
good small-monolith stack. The main improvement opportunity is not to split the
system into services, but to introduce clearer internal seams before feature
growth makes handlers, commands, and data access files too wide.

## Current Shape

- `cmd/oc` resolves the data directory and delegates to `internal/cli`.
- `internal/cli` owns Cobra commands and directly opens `internal/db`.
- `internal/api` owns HTTP routing, request validation, AI orchestration, and
  response shaping.
- `internal/db` owns schema, migrations, row models, and query methods.
- `internal/ai` owns provider calls, prompts, chat/tool orchestration, and
  model-call helpers.
- `web/src/services` mirrors backend REST endpoints with hand-written TypeScript
  types in `web/src/types`.
- `web/src/layout/AppShell.tsx` acts as the main frontend composition root.

## High-Priority Findings

### 1. Docker runtime stage likely cannot build from a clean context

`Dockerfile` builds the frontend in the `web` stage and copies it into the
backend stage, but the final stage uses `COPY web/dist /app/web/dist`.
`.dockerignore` excludes `web/dist`, so a clean Docker build context will not
contain that path. The final stage should copy from a build stage instead.

Impact: release builds may fail even though local `npm run build` and
`go build` pass.

Recommended fix:

```dockerfile
COPY --from=web /web/dist /app/web/dist
```

I could not run `docker build` in this environment because Docker is not
installed, but static inspection is decisive here.

### 2. API handlers are becoming application services

Several HTTP handlers now do more than transport work. For example, mock
interview session handling assembles prompt context, owns scoring flow, writes
retrospective notes, and handles persistence state transitions in one file.
Chat handling also constructs prompts, creates conversations, runs tool loops,
persists model messages, and handles provider fallback.

Impact: CLI and API cannot easily share workflow logic, and future behavior
changes become handler edits instead of use-case edits.

Recommended fix: introduce small use-case services under `internal/app` or
`internal/service`, starting only with the most workflow-heavy areas:

- `chat.Service`
- `mock.Service`
- `knowledge.Service` only if imports/search rules grow further

Keep `internal/api` responsible for HTTP shape and status codes.

### 3. Persistence is split into topic files, but schema migration is centralized

`internal/db/db.go` contains all core row types, table creation, indexes, and
compatibility `ensureColumn` calls. Topic files contain query methods. This is
workable now, but the schema has already grown into applications, events, notes,
resumes, JD analysis, matches, offers, chat, knowledge, questions, material
kits, and mock sessions.

Impact: migrations are hard to review, hard to order, and easy to accidentally
make non-idempotent as more features land.

Recommended fix: keep SQLite and the current `Database` wrapper, but move to
numbered migration steps:

- keep a `schema_migrations` table
- store migrations as ordered Go strings or embedded SQL files
- keep compatibility migrations explicit and test old-schema upgrades

Do not add a heavyweight migration framework unless the project outgrows simple
embedded migration steps.

## Medium-Priority Findings

### 4. Frontend/backend contracts are hand-maintained in two languages

TypeScript types intentionally mirror Go JSON tags, but there is no contract
generation or schema test. This is fine for a small API, but the number of
entities is now large enough that drift is likely.

Impact: backend field changes can silently break the UI until runtime.

Recommended fix: choose a light contract strategy:

- simplest: add API response shape tests for critical endpoints plus TypeScript
  compile-time fixtures
- stronger: generate OpenAPI from route DTOs and generate TS clients
- middle path: centralize DTOs in Go and add a small schema snapshot test

### 5. Frontend composition is centralized in `AppShell`

`AppShell` fetches global data, computes cross-feature insights, owns navigation
state, opens global modals, and wires many feature views. Lazy loading is already
used, which is good, but the shell is becoming a product orchestrator rather
than a layout component.

Impact: adding a new view requires editing a broad central file and risks
coupling unrelated feature state.

Recommended fix:

- keep `AppShell` as the top-level route/view switch
- move feature-specific query bundles into feature containers
- create a small navigation/action interface shared by dashboard, command
  palette, and reminders

### 6. Bundle output has a large shared chunk

`npm run build` succeeds, but Vite reports a `1,333.22 kB` minified chunk. Major
views are lazy-loaded, so this probably comes from shared Ant Design, icons,
React Query, markdown, or common components being pulled into a single chunk.

Impact: first load and refresh cost will grow as features accumulate.

Recommended fix:

- inspect bundle composition with a visualizer
- add `manualChunks` for `antd`, React/vendor, markdown, and chart-heavy code
- lazy-load large modal/drawer flows that are not needed on first paint

### 7. Dependency and documentation hygiene need a pass

`npm ci` reports five audit vulnerabilities. README says React 19, while
`web/package.json` uses React 18.3.1. Several Chinese strings render garbled in
terminal output, which suggests encoding consistency should be checked before
large copy-heavy edits.

Impact: quality signals drift, and dependency upgrades become harder when left
until urgent.

Recommended fix: schedule a separate maintenance branch for frontend dependency
audit, README correction, and encoding review.

## What Not To Optimize Yet

- Do not split the backend into microservices. Local-first single binary is a
  product advantage.
- Do not replace SQLite. The current single-user workload fits SQLite well.
- Do not introduce a large DI/container framework. Constructor injection and
  small service structs are enough.
- Do not rewrite the frontend routing stack unless deep linking becomes a
  product requirement.

## Recommended Sequence

1. Fix Docker final-stage copy.
2. Extract `mock` and `chat` use-case services from HTTP handlers.
3. Introduce ordered migrations and one old-schema upgrade test.
4. Add a lightweight API contract guard between Go DTOs and TypeScript types.
5. Split the large frontend vendor chunk with measured bundle output.
6. Run a dependency/docs/encoding maintenance pass.

## Verification Run

- `go mod download`: passed
- `go test ./...`: passed
- `npm.cmd ci`: passed, with 5 audit vulnerabilities reported
- `npm.cmd test`: passed, 29 frontend tests
- `npm.cmd run build`: passed, with large chunk warning
- `docker build -t offerpilot-arch-check .`: not run, Docker command missing
