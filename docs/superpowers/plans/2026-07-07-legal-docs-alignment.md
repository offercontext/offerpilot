# Legal Docs Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align OfferPilot's public license and README with the Feishu ADR decision that the open-source MVP uses AGPLv3.

**Architecture:** This is the first, smallest release-blocker slice from the project adjustment review. It changes repository-facing legal/docs artifacts only, leaving runtime behavior untouched so the branch remains easy to verify and merge.

**Tech Stack:** Markdown documentation, GNU AGPLv3 license text, existing Python/React verification commands.

---

## Scope Boundary

The broader roadmap contains independent subsystems: licensing/docs, status-machine domain contract, frontend information architecture, Pilot rail, model routing, persisted HITL state, Skill installation, and RAG. This plan intentionally implements only the legal/docs gate. The next plan should start with the backend-owned application status enum and compatibility migration.

## File Structure

- Modify: `LICENSE`
  - Responsibility: contain the full GNU Affero General Public License v3 text.
- Modify: `README.md`
  - Responsibility: state the AGPLv3 license consistently in Chinese and English, explain the local-first/self-hosted positioning, and remove MIT wording.
- Create: `CONTRIBUTING.md`
  - Responsibility: document contribution expectations, quality gates, and the ADR-001 note that external contribution licensing/CLA policy must be settled before broad external contribution intake.
- Reference only: `docs/superpowers/specs/2026-07-07-project-adjustments-review.md`
  - Responsibility: source rationale for why this slice comes first.

## Task 1: Replace MIT License With AGPLv3

**Files:**
- Modify: `LICENSE`

- [ ] **Step 1: Verify current failing state**

Run:

```powershell
Select-String -Path LICENSE -Pattern 'MIT License'
```

Expected: output includes `MIT License`, proving the repo conflicts with ADR-001.

- [ ] **Step 2: Replace `LICENSE` with AGPLv3**

Use the official GNU AGPLv3 text from `https://www.gnu.org/licenses/agpl-3.0.txt`. Keep the standard license text unchanged except normal line endings.

- [ ] **Step 3: Verify license changed**

Run:

```powershell
Select-String -Path LICENSE -Pattern 'GNU AFFERO GENERAL PUBLIC LICENSE'
Select-String -Path LICENSE -Pattern 'MIT License'
```

Expected: first command finds `GNU AFFERO GENERAL PUBLIC LICENSE`; second command returns no matches.

## Task 2: Update README License Positioning

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Verify current failing state**

Run:

```powershell
Select-String -Path README.md -Pattern 'MIT|AGPL|License|开源协议'
```

Expected: README includes MIT wording and does not consistently state AGPLv3.

- [ ] **Step 2: Update Chinese license section**

Replace the Chinese license paragraph with:

```markdown
### 📜 开源协议

[AGPLv3](LICENSE) — OfferPilot 是本地优先、自托管的开源求职工作台。你可以使用、修改和分发本项目；如果将修改后的版本通过网络提供给用户，也需要按 AGPLv3 向这些用户提供对应源码。
```

- [ ] **Step 3: Update English license section**

Replace the English license paragraph with:

```markdown
### 📜 License

[AGPLv3](LICENSE) — OfferPilot is a local-first, self-hosted open-source job-search workbench. You may use, modify, and distribute it; if you provide a modified version over a network, AGPLv3 requires making the corresponding source available to those users.
```

- [ ] **Step 4: Verify README consistency**

Run:

```powershell
Select-String -Path README.md -Pattern 'MIT'
Select-String -Path README.md -Pattern 'AGPLv3'
```

Expected: no `MIT` matches; at least two `AGPLv3` matches.

## Task 3: Add Contribution Policy Note

**Files:**
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Verify current state**

Run:

```powershell
Test-Path CONTRIBUTING.md
```

Expected: `False`.

- [ ] **Step 2: Create contribution guide**

Create `CONTRIBUTING.md` with:

```markdown
# Contributing to OfferPilot

Thanks for helping improve OfferPilot.

## License

OfferPilot is licensed under AGPLv3. By contributing, you agree that your contribution can be distributed under the project's AGPLv3 license.

Before the project broadly accepts external contributions, the maintainers should decide whether a CLA or DCO process is required. This follows ADR-001 so future licensing choices are not blocked by unclear contribution rights.

## Development

Use a feature branch or worktree for changes. Keep commits small and use the repository commit convention:

```text
<type>: AI <subject>
```

Valid types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style`, and `test`.

## Quality Gates

Run the relevant checks before opening a pull request:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
cd web && npm test
cd web && npm run build
```

For user-facing behavior changes, also run a local smoke check with `uv run oc start`.
```

- [ ] **Step 3: Verify contribution guide**

Run:

```powershell
Select-String -Path CONTRIBUTING.md -Pattern 'AGPLv3|CLA|DCO|uv run pytest'
```

Expected: matches all key contribution-policy and verification phrases.

## Task 4: Verification And Commit

**Files:**
- Modify: `LICENSE`
- Modify: `README.md`
- Create: `CONTRIBUTING.md`
- Existing plan: `docs/superpowers/plans/2026-07-07-legal-docs-alignment.md`

- [ ] **Step 1: Run repository checks**

Run:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
npm.cmd test
npm.cmd run build
```

Run the npm commands from `web/`.

Expected: all commands exit 0. If npm audit is printed during install only, do not run `npm audit fix --force` in this slice because it can introduce breaking dependency changes.

- [ ] **Step 2: Inspect diff**

Run:

```powershell
git diff -- LICENSE README.md CONTRIBUTING.md docs/superpowers/plans/2026-07-07-legal-docs-alignment.md
git status --short
```

Expected: only the planned docs/license files are modified or added.

- [ ] **Step 3: Stage files**

Run:

```powershell
git add LICENSE README.md CONTRIBUTING.md docs/superpowers/plans/2026-07-07-legal-docs-alignment.md
```

- [ ] **Step 4: Commit**

Run:

```powershell
git commit -m "docs: AI align license documentation"
```

Expected: commit succeeds with the conventional commit format required by the repository instructions.
