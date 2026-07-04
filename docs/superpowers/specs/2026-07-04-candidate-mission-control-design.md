# Candidate Mission Control Design

- **Date**: 2026-07-04
- **Branch**: `codex/feat-product-roadmap`
- **Worktree**: `D:\Users\yuqi.chen\offerpilot\.worktrees\codex-feat-product-roadmap`
- **Status**: Direction approved; ready for user review before implementation planning

## 1. First Principles

OfferPilot should help a candidate improve the odds of getting a good offer while reducing the mental load of managing a complex job search. The product already has strong individual tools:

- application tracking
- schedule and reminders
- resume library and material kits
- JD analysis and resume matching
- interview retrospectives
- knowledge base and question practice
- mock interview studio
- offer comparison and negotiation coaching
- pipeline intelligence and command palette

The next gap is not another isolated tool. The user needs a control layer that turns all existing modules into a weekly operating loop: set the target, see the current state, choose today's actions, prepare the right materials, practice against weak spots, and review progress.

The recommended feature is **Candidate Mission Control**: a local-first planning and execution surface that connects goals, pipeline health, preparation, and outcomes into one daily workbench.

## 2. Product Goal

Mission Control answers four questions every time the user opens OfferPilot:

1. What am I trying to achieve this week?
2. What is blocking progress right now?
3. What should I do today?
4. Which application or offer needs focused preparation?

The feature should feel like a calm operations console, not a generic task manager. Every action must tie back to an existing job-search object: an application, event, offer, resume, material kit, question, mock session, or review note.

## 3. MVP Scope

### Includes

1. **Weekly Mission Panel**
   - Shows a weekly target summary: applications, follow-ups, interviews, practice, material readiness, and offer deadlines.
   - Uses transparent default targets first, with editable settings deferred unless the implementation cost is low.
   - Highlights the largest gap and the next best action.

2. **Today Action Plan**
   - Reuses `derivePipelineInsights` as the action source.
   - Groups actions into "urgent", "prepare", and "maintain momentum".
   - Supports quick navigation to the right existing module or detail drawer.
   - Explains why each action exists using existing evidence strings.

3. **Application Readiness Strip**
   - Shows the most important active applications with readiness states:
     - material kit status
     - upcoming event status
     - follow-up freshness
     - practice readiness
     - latest review or mock signal when available
   - Prioritizes active applications over archived or rejected ones.

4. **Focus Workspace**
   - Lets the user select one application or offer as the current focus.
   - Shows connected context: JD/material kit, schedule, questions due, mock interview entry, notes, and offer actions.
   - Keeps editing in existing drawers/pages rather than duplicating forms.

5. **Design System Polish**
   - Preserve the current Ant Design + OfferPilot token system.
   - Add a clearer action color role for primary execution states without replacing the brand palette.
   - Tighten responsive behavior for dense dashboard layouts.
   - Improve typography, hit areas, focus states, and reduced-motion behavior.

### Out of Scope

- External job scraping or opportunity ingestion.
- A general task database unrelated to job-search entities.
- Calendar sync with third-party accounts.
- Automatic background AI generation.
- Full visual redesign or UI framework replacement.
- Predictive scoring that cannot explain its inputs.
- Multi-user collaboration or cloud sync.

## 4. Information Architecture

Mission Control should become the dashboard's primary first screen, while preserving current dashboard widgets below or beside it.

Recommended page structure:

1. **Mission Header**
   - Week range.
   - Pipeline health label.
   - One short strategic sentence.
   - Primary CTA for the next best action.

2. **Weekly Mission Panel**
   - Compact progress metrics with tabular numbers.
   - Each metric includes target, current value, and state label.
   - Color is never the only state indicator.

3. **Today Action Plan**
   - A dense list of top actions.
   - Each row has priority, title, reason, evidence hint, and one primary action.
   - Clicking the row opens `ActionDetailDrawer`.

4. **Readiness Strip**
   - Horizontal or responsive grid of active application readiness cards.
   - Each card exposes status chips and one "focus" action.

5. **Focus Workspace**
   - A right-side panel on desktop.
   - A drawer or stacked section on mobile.
   - Shows context and links into existing modules.

Existing dashboard widgets such as KPI cards, conversion funnel, momentum chart, and upcoming schedule should remain available, but they should not compete with the action plan for first-screen attention.

## 5. Data Model

The MVP should derive most state in the frontend from existing queries:

- `applications`
- `events`
- `offers`
- question practice stats
- material kit view models
- resumes where needed for readiness context

No new table is required for the first implementation. A focused derived model can live in `web/src/lib/missionControl.ts`.

```ts
export type MissionMetricKind =
  | 'applications'
  | 'followups'
  | 'interviews'
  | 'practice'
  | 'materials'
  | 'offers';

export type MissionMetricState = 'on_track' | 'watch' | 'behind' | 'blocked';

export interface MissionMetric {
  kind: MissionMetricKind;
  label: string;
  current: number;
  target?: number;
  state: MissionMetricState;
  reason: string;
  targetView: ViewMode;
}

export interface ApplicationReadiness {
  applicationId: number;
  companyName: string;
  positionName: string;
  status: ApplicationStatus;
  readiness: 'ready' | 'watch' | 'blocked';
  materialStatus?: 'missing' | 'draft' | 'ready' | 'submitted';
  hasUpcomingEvent: boolean;
  staleDays?: number;
  dueQuestionCount?: number;
  evidence: string[];
}

export interface MissionControlSummary {
  weekStart: string;
  weekEnd: string;
  headline: string;
  healthLabel: PipelineHealth['label'];
  metrics: MissionMetric[];
  actions: PipelineInsight[];
  readiness: ApplicationReadiness[];
  focusApplicationId?: number;
}
```

If user-editable weekly targets become necessary, add a small settings API later rather than blocking the MVP.

## 6. Derivation Rules

### Weekly Metrics

Default targets should be conservative and explicit:

- applications: 6 per week
- follow-ups: 3 per week when stale applications exist
- interviews: count scheduled interviews and assessments this week; no fixed target
- practice: at least one due-question practice session when due questions exist
- materials: active applications should have a material kit that is `ready` or `submitted`
- offers: pending or negotiating offers should have no deadline within 48 hours without a next action

Metric states:

- `on_track`: current progress is enough or no action is needed.
- `watch`: progress is slightly behind or a deadline is approaching.
- `behind`: progress is meaningfully behind the target.
- `blocked`: a missing material, imminent deadline, or missing next event prevents progress.

### Readiness

Readiness should favor explainability:

- `blocked`: active application has an imminent event without material readiness, or an offer deadline is within 48 hours.
- `watch`: stale waiting application, missing next event in interview stage, draft material kit, or due practice items.
- `ready`: material and schedule state are sufficient, or no immediate preparation gap exists.

### Actions

Mission Control should not invent a second action engine. It should reuse `PipelineInsight` and only add presentation grouping:

- urgent: `p0`
- prepare: interview soon, material kit incomplete, question due, offer deadline
- maintain momentum: stale applications, no next event, bottleneck, weekly goal gap

## 7. Interface Design

The UI should remain a dense, calm productivity tool for repeated daily use.

### Visual Direction

Use the current Ant Design components and OfferPilot tokens. Preserve the purple-blue brand gradient for AI and identity moments, but introduce a stronger action accent token for execution states:

- `--op-action`: a warm orange for primary next actions and deadline attention.
- `--op-action-soft`: a pale action background for selected action rows.
- `--op-info`: a blue/teal role for neutral guidance and readiness.

Avoid a full palette swap. The product already has a recognizable visual system, and this feature should strengthen hierarchy rather than repaint the app.

### Layout

Desktop:

- Mission header spans the top.
- Weekly mission metrics use a compact responsive grid.
- Today Action Plan takes the primary left column.
- Focus Workspace sits in the right column.
- Readiness Strip can sit between the mission metrics and action plan, or below the action plan depending on density.

Mobile:

- Stack mission header, metrics, action plan, readiness, then focus.
- Convert Focus Workspace to an Ant Design drawer when opened from an application readiness card.
- Keep all rows within viewport width; no horizontal scrolling except intentionally scrollable compact strips.

### Polish Rules

- Use `font-variant-numeric: tabular-nums` for counts, dates, percentages, salary, and progress values.
- Apply `text-wrap: balance` to short headers and `text-wrap: pretty` to descriptions.
- Use at least 44x44px hit targets for action rows, icon buttons, and readiness card controls.
- Prefer explicit transitions such as `box-shadow`, `background-color`, `opacity`, and `transform`; avoid `transition: all`.
- Keep reduced-motion behavior consistent with existing `prefers-reduced-motion`.
- Use shadows as depth rings for repeated action/readiness surfaces when a border looks too flat.
- Do not use emoji as UI icons. Continue using Ant Design icons unless the project standard changes.

## 8. Component Plan

Recommended frontend units:

- `web/src/lib/missionControl.ts`
  - Derives metrics, readiness, headline, and action groupings.
  - Contains deterministic helpers with unit tests.

- `web/src/features/dashboard/widgets/MissionHeader.tsx`
  - Shows week range, health label, strategic sentence, and next action CTA.

- `web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx`
  - Renders compact metric tiles with target/current/state.

- `web/src/features/dashboard/widgets/TodayActionPlan.tsx`
  - Renders grouped `PipelineInsight` rows and opens `ActionDetailDrawer`.

- `web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx`
  - Renders prioritized active applications and focus actions.

- `web/src/features/dashboard/widgets/FocusWorkspace.tsx`
  - Shows connected context and routes to existing modules.

`DashboardView` should orchestrate data fetching and pass derived summaries down. Avoid moving query logic into every widget.

## 9. Error Handling

- If optional sources fail, degrade gracefully:
  - question stats unavailable: hide practice metric or mark it as unavailable.
  - material kits unavailable: show material status as unknown, not blocked.
  - offers unavailable: omit offer pressure metric.
- Keep action navigation resilient. If an action points to a missing application, close the drawer and show a clear inline fallback.
- Empty state should invite adding the first application and uploading a resume, not show a blank dashboard.
- AI-related actions must stay explicit user actions. Mission Control can suggest a draft, but should not call AI automatically.

## 10. Testing Strategy

Frontend unit tests:

- weekly metric target calculation
- metric state transitions
- readiness classification
- action grouping
- headline selection
- null/empty backend arrays
- optional data-source degradation

Frontend verification:

- `npm.cmd test`
- `npm.cmd run build`

Backend verification:

- `go test ./...`

Browser verification after implementation:

- Desktop dashboard shows Mission Control first.
- Empty state works with zero applications.
- Action rows open `ActionDetailDrawer`.
- Focus Workspace links to existing modules without duplicating forms.
- Mobile width avoids overlap and horizontal scroll.
- Keyboard focus is visible on rows, buttons, and drawer controls.
- Reduced-motion preference does not break layout.

## 11. Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Dashboard becomes too busy | Make Today Action Plan the primary surface and move secondary analytics lower. |
| Metrics feel arbitrary | Show targets and reasons directly in each metric. Keep defaults conservative. |
| Feature duplicates reminders | Mission Control is a daily summary; Reminders remains the full searchable action center. |
| Focus Workspace duplicates existing forms | Link into existing drawers/pages instead of rebuilding editors. |
| Material kit lookups add query cost | Start with active applications only and cache via React Query. |
| Bundle size grows | Keep widgets lightweight and avoid adding new chart or animation libraries. |
| Mobile density suffers | Use stacked sections and drawer focus mode below 700px. |

## 12. Implementation Sequence

The implementation plan should be written after this spec is reviewed. Recommended sequence:

1. Add `missionControl.ts` derivation helpers and unit tests.
2. Add Mission Header and Weekly Mission Panel.
3. Add Today Action Plan using existing `ActionDetailDrawer`.
4. Add Application Readiness Strip.
5. Add Focus Workspace with navigation into existing modules.
6. Polish responsive behavior, accessibility, and token usage.
7. Run full verification and inspect bundle output.

## 13. Follow-Up Foundation Work

During research, several non-feature improvements stood out:

- Chinese copy appears garbled in multiple source files and should be repaired before large copy-heavy work.
- Vite still reports large chunks after lazy-loading major views; manual chunking or further lazy modal loading should be considered.
- `npm install` reports 5 audit vulnerabilities; dependency upgrades need a separate risk-managed pass.
- README now aligns the frontend stack with `package.json` by documenting React 18.

These items should not block Mission Control, but they are likely to affect perceived quality and maintainability.
