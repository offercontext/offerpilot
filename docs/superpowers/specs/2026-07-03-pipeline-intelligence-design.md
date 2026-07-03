# Pipeline Intelligence Design

- **Date**: 2026-07-03
- **Branch**: `feat/product-opportunity-research`
- **Worktree**: `D:\Users\yuqi.chen\offerpilot\.worktrees\feat-product-opportunity-research`
- **Status**: Approved through brainstorming; ready for implementation planning

## 1. First Principles

OfferPilot's core goal is not to store job-search records. Its job is to help a candidate raise the probability of getting a suitable offer while reducing the operational burden of managing many moving parts.

The current product already covers the main job-search lifecycle:

- application tracking
- JD analysis and resume matching
- schedule and reminders
- interview retrospectives
- knowledge base and question practice
- mock interview studio
- offer comparison and negotiation coaching
- AI assistant

The next high-leverage gap is not another isolated page. It is turning existing data into active judgment: what should the user do next, why it matters, what context is relevant, and how the result feeds back into the job-search loop.

The recommended feature is **Pipeline Intelligence**: an explainable, local-first decision layer over the existing dashboard, reminders, command palette, and AI assistant.

## 2. Product Scope

Pipeline Intelligence upgrades OfferPilot from a record-keeping workbench into a daily operating console.

### MVP Includes

1. **Pipeline Diagnostics**
   - Derive transparent, testable insights from existing local data.
   - Explain why each insight exists with evidence.
   - Rank insights by urgency, impact, and deadline.

2. **Action Detail Drawer**
   - Clicking a dashboard or reminder action opens an explainable detail view.
   - The drawer shows reason, evidence, recommended next steps, and relevant context links.
   - AI generation is offered as an explicit user action, not an automatic background call.

3. **Weekly Strategy Review**
   - Summarize channel momentum, stage bottlenecks, stale applications, upcoming deadlines, and next-week goals.
   - Keep the first version rule-based and transparent rather than predictive.

4. **UX Foundation**
   - Add route-level lazy loading for major views.
   - Improve command palette action access.
   - Ensure mobile layout, focus states, hit areas, and reduced-motion behavior are solid.

### Explicitly Out of Scope

- External job scraping or opportunity ingestion.
- A generic task-management system.
- Black-box prediction or scoring models.
- Database persistence for derived insights.
- New UI framework or major visual redesign.
- Automatic AI calls without user intent.

## 3. Data Model

The MVP should not add a new table. Insights are derived at runtime from existing entities:

- `applications`
- `events`
- `offers`
- question practice stats
- material kit state

The current `ActionItem` model should evolve into an explainable `PipelineInsight` model. A compatibility wrapper can preserve existing dashboard/reminder behavior while the UI migrates.

```ts
type PipelineInsight = {
  id: string;
  kind:
    | 'offer_deadline'
    | 'interview_soon'
    | 'stale_application'
    | 'no_next_event'
    | 'material_kit_incomplete'
    | 'question_due'
    | 'pipeline_bottleneck'
    | 'weekly_goal_gap';
  priority: 'p0' | 'p1' | 'p2';
  title: string;
  reason: string;
  evidence: string[];
  impact: string;
  primaryAction: ActionCommand;
  secondaryActions: ActionCommand[];
  target: ViewMode;
  sortKey: number;
  appId?: number;
  offerId?: number;
  eventId?: number;
  questionCount?: number;
};

type ActionCommand = {
  id: string;
  label: string;
  kind: 'navigate' | 'open_detail' | 'open_drawer' | 'open_ai_draft';
  target?: ViewMode;
};
```

### Rule Priorities

`P0`:

- Offer deadline is within 48 hours.
- Interview or assessment is within 24 hours.
- A critical application material gap blocks an imminent step.

`P1`:

- Offer deadline is within 7 days.
- Interview or assessment is within 72 hours.
- Waiting application has been stale for 14 days or more.
- Due practice-question count is high.

`P2`:

- Waiting application has been stale for more than 7 days.
- Application is in interview stage but has no future scheduled event.
- Material kit is missing or incomplete.
- Weekly application or practice rhythm is below target.

### Aggregate Insights

`pipeline_bottleneck`:

- Detect stage pileups, such as many applications stuck in initial screening.
- Detect weak conversion points, such as interview-to-offer underperformance.
- Explain using counts and ratios, not opaque scores.

`weekly_goal_gap`:

- Compare weekly application count and practice progress against simple configurable defaults.
- The first version can hard-code conservative defaults and later expose settings.

## 4. Interface Design

The UI should remain a dense, calm productivity tool. It should extend Ant Design and the existing OfferPilot token system instead of introducing a new visual language.

### Dashboard

The dashboard first screen becomes a decision panel:

1. **Today Command Center**
   - Shows the top 3-5 `PipelineInsight` items.
   - Each item includes priority, title, short reason, and a primary action.

2. **Pipeline Health**
   - Shows health score, largest bottleneck, and weekly rhythm.
   - Numbers use `font-variant-numeric: tabular-nums`.
   - Color is paired with text labels so state is not conveyed by color alone.

3. **Strategy Snapshot**
   - Shows application funnel, recent application momentum, and stage pileups.
   - Keeps charting lightweight and accessible.

### Action Detail Drawer

`ActionDetailDrawer` should be shared by dashboard and reminders.

Sections:

- Header: priority, title, company/position when applicable.
- Why this appears: `reason` plus evidence list.
- Recommended next steps: primary action and secondary actions.
- Related context: links to application detail, material kit, notes, schedule, question bank, or offer center.
- AI draft: explicit generation entry for follow-up messages, interview preparation, or negotiation replies.

Errors and unavailable actions should be shown inline, near the affected action. Toasts can supplement but should not be the only feedback.

### Reminders

Reminders becomes a full action center:

- Group by `P0`, `P1`, and `P2`.
- Filter by insight kind, company, and deadline state.
- Open the same `ActionDetailDrawer`.
- Empty state should suggest light next actions, such as adding applications, practicing due questions, or writing a retrospective.

### Command Palette

The command palette keeps application search and navigation, then adds:

- Recent applications.
- Highest-priority pipeline actions.
- Verb-like entry points such as follow up, prepare interview, negotiate, upload resume, and review week.

### UX Foundation

- Use `React.lazy` and `Suspense` for major views in `AppShell`.
- Keep hit areas at least 44px where possible.
- Add accessible names to icon-only and shortcut-style controls.
- Avoid `transition: all`; animate specific properties only.
- Keep `prefers-reduced-motion` support.
- For mobile, collapse the sidebar into a top or drawer navigation pattern.

## 5. Implementation Plan Outline

The detailed implementation plan should be written separately, but the recommended sequence is:

1. Add `PipelineInsight` derivation and tests.
2. Add compatibility helpers for current `ActionItem` consumers.
3. Upgrade dashboard command center and supporting widgets.
4. Add shared `ActionDetailDrawer`.
5. Upgrade reminders into the action center.
6. Upgrade command palette.
7. Add route-level lazy loading and responsive navigation polish.

## 6. Testing Strategy

Frontend unit tests:

- Priority assignment for P0/P1/P2 rules.
- Sorting by priority and sort key.
- Evidence and reason generation.
- Bottleneck and weekly gap derivation.
- Compatibility with existing dashboard/reminder action consumers.

Frontend build verification:

- `npm.cmd test`
- `npm.cmd run build`

Backend verification:

- `go test ./...`

Browser verification after implementation:

- Dashboard shows top insights and health summary.
- Clicking an action opens the detail drawer.
- Reminders filters and groups insights correctly.
- Command palette exposes high-priority actions.
- Mobile width does not overlap or create horizontal scroll.
- Reduced-motion preference does not break the experience.

## 7. Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Insight rules feel arbitrary | Show explicit evidence and keep thresholds test-covered. |
| Dashboard becomes visually busy | Limit the first screen to top actions and summary widgets. |
| Scope drifts into task management | Actions must resolve back to existing job-search objects. |
| AI calls become surprising | Keep generation behind explicit user clicks. |
| Bundle grows further | Add route-level lazy loading as part of the feature. |
| Mobile usability regresses | Include mobile navigation and no-overlap checks in verification. |

## 8. Open Follow-Up

After this spec is reviewed, the next step is a detailed implementation plan. The plan should preserve the existing local-first architecture, avoid database changes for MVP, and keep edits scoped to the pipeline insight model plus the dashboard/reminders/command palette surfaces.
