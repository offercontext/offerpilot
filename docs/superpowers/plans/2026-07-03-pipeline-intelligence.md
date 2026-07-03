# Pipeline Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an explainable Pipeline Intelligence layer that upgrades Dashboard, Reminders, and Command Palette into a daily job-search operating console.

**Architecture:** Keep all insights derived from existing local data in the frontend first, without adding database tables. Introduce a focused `pipelineInsights` library, keep a compatibility adapter for existing `ActionItem` consumers, then migrate Dashboard and Reminders onto shared insight UI pieces.

**Tech Stack:** Go backend unchanged for MVP; React 18, TypeScript, Vite, Ant Design, TanStack Query, dayjs, CSS modules, Vitest.

---

## File Structure

- Create `web/src/lib/pipelineInsights.ts`
  - Owns `PipelineInsight`, `ActionCommand`, health summary, bottleneck, weekly-gap derivation, sorting, and compatibility conversion.
- Create `web/src/lib/pipelineInsights.test.ts`
  - Unit tests for insight rules, priority, evidence, sorting, health summary, and compatibility behavior.
- Modify `web/src/lib/actionItems.ts`
  - Re-export or delegate to `pipelineInsights` where needed so old imports keep working during migration.
- Create `web/src/features/pipeline/ActionDetailDrawer.tsx`
  - Shared explainable detail drawer for Dashboard and Reminders.
- Create `web/src/features/pipeline/pipeline.module.css`
  - Drawer and shared pipeline interaction styling.
- Modify `web/src/features/dashboard/DashboardView.tsx`
  - Use `derivePipelineInsights` and pass selected insight state into dashboard widgets.
- Modify `web/src/features/dashboard/widgets/CommandCenter.tsx`
  - Show top insights, health summary, and strategy snapshot hooks.
- Modify `web/src/features/dashboard/widgets/ActionQueue.tsx`
  - Render `PipelineInsight` cards and open detail drawer.
- Modify `web/src/features/dashboard/widgets/WeeklyRhythm.tsx`
  - Use health/weekly gap summary instead of only action count.
- Modify `web/src/features/reminders/RemindersView.tsx`
  - Upgrade to grouped, filterable action center and shared detail drawer.
- Modify `web/src/features/reminders/reminders.module.css`
  - Add filters, grouped cards, mobile-safe layout.
- Modify `web/src/layout/CommandPalette.tsx`
  - Add recent applications and highest-priority pipeline actions.
- Modify `web/src/layout/AppShell.tsx`
  - Route-level `React.lazy` for major views and pass pipeline action handlers.
- Modify `web/src/layout/Sidebar.tsx`
  - Add responsive drawer/top navigation support if needed for mobile.
- Modify `web/src/theme/tokens.css`
  - Add narrowly scoped utility tokens/classes only if required by new shared UI.

---

### Task 1: Pipeline Insight Model And Rules

**Files:**
- Create: `web/src/lib/pipelineInsights.ts`
- Create: `web/src/lib/pipelineInsights.test.ts`
- Modify: `web/src/lib/actionItems.ts`

- [ ] **Step 1: Write failing tests for offer deadline, stale application, and due question insights**

Add `web/src/lib/pipelineInsights.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import type { Offer } from '@/types/offer';
import { derivePipelineInsights } from './pipelineInsights';

const now = dayjs('2026-07-03T09:00:00+08:00');

function app(overrides: Partial<Application>): Application {
  return {
    id: 1,
    company_name: 'ByteDance',
    position_name: 'Backend Engineer',
    job_url: '',
    status: 'applied',
    source: 'web',
    notes: '',
    applied_at: '2026-06-20T09:00:00+08:00',
    created_at: '2026-06-20T09:00:00+08:00',
    updated_at: '2026-06-20T09:00:00+08:00',
    ...overrides,
  };
}

function offer(overrides: Partial<Offer>): Offer {
  return {
    id: 10,
    application_id: 1,
    company_name: 'ByteDance',
    position_name: 'Backend Engineer',
    status: 'pending',
    base_monthly: 30000,
    months_per_year: 15,
    signing_bonus: 0,
    equity: '',
    perks: '',
    deadline: '2026-07-04',
    notes: '',
    assessment: '',
    total_cash: 450000,
    created_at: '2026-07-01T09:00:00+08:00',
    updated_at: '2026-07-01T09:00:00+08:00',
    ...overrides,
  };
}

describe('derivePipelineInsights', () => {
  it('marks an offer deadline within 48 hours as P0 with evidence', () => {
    const insights = derivePipelineInsights({
      apps: [app({ status: 'offer' })],
      events: [],
      offers: [offer({ deadline: '2026-07-04' })],
      now,
    });

    const item = insights.find((x) => x.kind === 'offer_deadline');
    expect(item?.priority).toBe('p0');
    expect(item?.reason).toContain('Offer deadline');
    expect(item?.evidence).toContain('Deadline: 2026-07-04');
    expect(item?.primaryAction.label).toBe('Open offer center');
  });

  it('marks an application stale for 14 days as P1', () => {
    const insights = derivePipelineInsights({
      apps: [app({ updated_at: '2026-06-18T09:00:00+08:00' })],
      events: [],
      offers: [],
      now,
    });

    const item = insights.find((x) => x.kind === 'stale_application');
    expect(item?.priority).toBe('p1');
    expect(item?.reason).toContain('15 days without updates');
    expect(item?.target).toBe('board');
  });

  it('adds due-question insight when practice stats has due items', () => {
    const insights = derivePipelineInsights({
      apps: [],
      events: [],
      offers: [],
      practiceStats: { total: 20, due: 12, new: 3, practicing: 10, mastered: 7 },
      now,
    });

    const item = insights.find((x) => x.kind === 'question_due');
    expect(item?.priority).toBe('p1');
    expect(item?.questionCount).toBe(12);
    expect(item?.primaryAction.target).toBe('questions');
  });
});
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
npm.cmd test -- pipelineInsights.test.ts
```

Expected: fails because `./pipelineInsights` does not exist.

- [ ] **Step 3: Implement the minimal insight model and rules**

Create `web/src/lib/pipelineInsights.ts`:

```ts
import dayjs, { type ConfigType } from 'dayjs';
import type { Application, ApplicationStatus } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { Offer } from '@/types/offer';
import type { PracticeStats } from '@/types/question';
import type { ViewMode } from '@/layout/AppShell';

export type PipelinePriority = 'p0' | 'p1' | 'p2';
export type PipelineInsightKind =
  | 'offer_deadline'
  | 'interview_soon'
  | 'stale_application'
  | 'no_next_event'
  | 'material_kit_incomplete'
  | 'question_due'
  | 'pipeline_bottleneck'
  | 'weekly_goal_gap';

export interface ActionCommand {
  id: string;
  label: string;
  kind: 'navigate' | 'open_detail' | 'open_drawer' | 'open_ai_draft';
  target?: ViewMode;
}

export interface PipelineInsight {
  id: string;
  kind: PipelineInsightKind;
  priority: PipelinePriority;
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
}

export interface PipelineHealth {
  score: number;
  label: 'healthy' | 'watch' | 'risk';
  bottleneck: string;
  weeklyApplications: number;
  weeklyTarget: number;
}

interface MaterialKitActionState {
  application_id: number;
  complete: boolean;
}

interface DerivePipelineInsightsInput {
  apps: Application[];
  events: ScheduleEvent[];
  offers: Offer[];
  materialKits?: MaterialKitActionState[];
  practiceStats?: PracticeStats | null;
  now?: ConfigType;
  weeklyTarget?: number;
}

const WAITING_STATUSES: ApplicationStatus[] = ['applied', 'assessment', 'written_test'];
const PRIORITY_RANK: Record<PipelinePriority, number> = { p0: 0, p1: 1, p2: 2 };

function appName(app: Pick<Application, 'company_name' | 'position_name'>): string {
  return `${app.company_name} 路 ${app.position_name}`;
}

function parseDate(value: string): dayjs.Dayjs | null {
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed : null;
}

function primary(label: string, target: ViewMode): ActionCommand {
  return { id: `go-${target}`, label, kind: 'navigate', target };
}

export function derivePipelineInsights({
  apps,
  events,
  offers,
  materialKits,
  practiceStats,
  now = dayjs(),
  weeklyTarget = 6,
}: DerivePipelineInsightsInput): PipelineInsight[] {
  const current = dayjs(now);
  const insights: PipelineInsight[] = [];

  for (const offer of offers) {
    if (!['pending', 'negotiating'].includes(offer.status) || !offer.deadline) continue;
    const deadline = parseDate(offer.deadline);
    if (!deadline) continue;
    const hours = deadline.endOf('day').diff(current, 'hour', true);
    if (hours < 0 || hours > 24 * 7) continue;
    const priority: PipelinePriority = hours <= 48 ? 'p0' : 'p1';
    insights.push({
      id: `offer-${offer.id}`,
      kind: 'offer_deadline',
      priority,
      title: `${offer.company_name} offer needs a decision`,
      reason: `Offer deadline is within ${Math.ceil(hours / 24)} day(s).`,
      evidence: [`Deadline: ${offer.deadline}`, `Status: ${offer.status}`],
      impact: 'A missed deadline can remove negotiation leverage or cause the offer to expire.',
      primaryAction: primary('Open offer center', 'offers'),
      secondaryActions: [{ id: 'draft-negotiation', label: 'Draft negotiation reply', kind: 'open_ai_draft' }],
      target: 'offers',
      offerId: offer.id,
      appId: offer.application_id ?? undefined,
      sortKey: hours,
    });
  }

  for (const app of apps) {
    if (!WAITING_STATUSES.includes(app.status)) continue;
    const base = parseDate(app.updated_at || app.applied_at);
    if (!base) continue;
    const days = current.diff(base, 'day');
    if (days <= 7) continue;
    insights.push({
      id: `stale-${app.id}`,
      kind: 'stale_application',
      priority: days >= 14 ? 'p1' : 'p2',
      title: `${appName(app)} has gone quiet`,
      reason: `${days} days without updates.`,
      evidence: [`Current status: ${app.status}`, `Last update: ${base.format('YYYY-MM-DD')}`],
      impact: 'Stale applications make the pipeline look fuller than it is and hide where follow-up is needed.',
      primaryAction: primary('Open application', 'board'),
      secondaryActions: [
        { id: 'draft-follow-up', label: 'Draft follow-up message', kind: 'open_ai_draft' },
        { id: 'schedule-follow-up', label: 'Schedule follow-up', kind: 'navigate', target: 'calendar' },
      ],
      target: 'board',
      appId: app.id,
      sortKey: 1000 - days,
    });
  }

  const futureEventAppIds = new Set(
    events
      .filter((event) => event.scheduled_at && dayjs(event.scheduled_at).isAfter(current))
      .map((event) => event.application_id),
  );
  for (const app of apps) {
    if (app.status !== 'interview' || futureEventAppIds.has(app.id)) continue;
    insights.push({
      id: `no-next-${app.id}`,
      kind: 'no_next_event',
      priority: 'p2',
      title: `${appName(app)} needs the next interview step`,
      reason: 'Application is in interview stage but has no future scheduled event.',
      evidence: ['Status: interview', 'No upcoming event found'],
      impact: 'Missing next steps make interview preparation and follow-up harder to plan.',
      primaryAction: primary('Schedule next step', 'calendar'),
      secondaryActions: [{ id: 'open-application', label: 'Open application', kind: 'open_detail', target: 'board' }],
      target: 'calendar',
      appId: app.id,
      sortKey: 2500,
    });
  }

  if (materialKits) {
    const kitByApp = new Map(materialKits.map((kit) => [kit.application_id, kit]));
    for (const app of apps) {
      if (!WAITING_STATUSES.includes(app.status)) continue;
      if (kitByApp.get(app.id)?.complete) continue;
      insights.push({
        id: `material-kit-${app.id}`,
        kind: 'material_kit_incomplete',
        priority: 'p2',
        title: `${appName(app)} material kit is incomplete`,
        reason: 'Resume advice, outreach copy, or submission checklist still needs work.',
        evidence: ['Material kit is missing or incomplete'],
        impact: 'Incomplete materials can slow down application execution.',
        primaryAction: primary('Open application', 'board'),
        secondaryActions: [{ id: 'draft-materials', label: 'Draft materials', kind: 'open_ai_draft' }],
        target: 'board',
        appId: app.id,
        sortKey: 2200,
      });
    }
  }

  const due = practiceStats?.due ?? 0;
  if (due > 0) {
    insights.push({
      id: 'questions-due',
      kind: 'question_due',
      priority: due >= 10 ? 'p1' : 'p2',
      title: `${due} practice question(s) are due`,
      reason: `${due} question(s) are ready for review.`,
      evidence: [`Due questions: ${due}`],
      impact: 'Clearing due questions keeps interview recall fresh.',
      primaryAction: primary('Start practice', 'questions'),
      secondaryActions: [{ id: 'review-week', label: 'Review weak spots', kind: 'navigate', target: 'reviews' }],
      target: 'questions',
      questionCount: due,
      sortKey: 3000 - Math.min(due, 50),
    });
  }

  const weeklyApplications = apps.filter((app) => {
    const applied = parseDate(app.applied_at);
    return Boolean(applied && current.diff(applied, 'day') < 7);
  }).length;
  if (weeklyApplications < weeklyTarget) {
    insights.push({
      id: 'weekly-goal-gap',
      kind: 'weekly_goal_gap',
      priority: 'p2',
      title: 'Weekly application rhythm is below target',
      reason: `${weeklyApplications}/${weeklyTarget} applications logged in the last 7 days.`,
      evidence: [`Weekly applications: ${weeklyApplications}`, `Target: ${weeklyTarget}`],
      impact: 'A thin top of funnel reduces downstream interview and offer chances.',
      primaryAction: primary('Add application', 'board'),
      secondaryActions: [{ id: 'open-dashboard', label: 'Review dashboard', kind: 'navigate', target: 'dashboard' }],
      target: 'board',
      sortKey: 3500,
    });
  }

  return insights.sort(
    (a, b) => PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] || a.sortKey - b.sortKey,
  );
}

export function summarizePipelineHealth(apps: Application[], insights: PipelineInsight[], weeklyTarget = 6): PipelineHealth {
  const p0 = insights.filter((item) => item.priority === 'p0').length;
  const p1 = insights.filter((item) => item.priority === 'p1').length;
  const weeklyApplications = apps.filter((app) => dayjs().diff(dayjs(app.applied_at), 'day') < 7).length;
  const score = Math.max(0, Math.min(100, 100 - p0 * 20 - p1 * 8));
  const bottleneck = insights.find((item) => item.kind === 'pipeline_bottleneck')?.title
    ?? insights.find((item) => item.kind === 'stale_application')?.title
    ?? 'No major bottleneck detected';
  return {
    score,
    label: score >= 80 ? 'healthy' : score >= 55 ? 'watch' : 'risk',
    bottleneck,
    weeklyApplications,
    weeklyTarget,
  };
}
```

- [ ] **Step 4: Add compatibility adapter for existing action consumers**

Append to `web/src/lib/pipelineInsights.ts`:

```ts
export interface LegacyActionItem {
  id: string;
  kind: PipelineInsightKind;
  priority: PipelinePriority;
  title: string;
  detail: string;
  primaryActionLabel: string;
  target: 'board' | 'calendar' | 'offers' | 'questions';
  sortKey: number;
  appId?: number;
  offerId?: number;
  eventId?: number;
  questionCount?: number;
}

export function toLegacyActionItems(insights: PipelineInsight[]): LegacyActionItem[] {
  return insights
    .filter((item): item is PipelineInsight & { target: LegacyActionItem['target'] } =>
      ['board', 'calendar', 'offers', 'questions'].includes(item.target),
    )
    .map((item) => ({
      id: item.id,
      kind: item.kind,
      priority: item.priority,
      title: item.title,
      detail: item.reason,
      primaryActionLabel: item.primaryAction.label,
      target: item.target,
      sortKey: item.sortKey,
      appId: item.appId,
      offerId: item.offerId,
      eventId: item.eventId,
      questionCount: item.questionCount,
    }));
}
```

Modify `web/src/lib/actionItems.ts` only after the new tests pass. Keep existing public exports available while migrating UI:

```ts
export {
  derivePipelineInsights,
  summarizePipelineHealth,
  toLegacyActionItems,
  type PipelineInsight,
  type PipelinePriority as ActionItemPriority,
  type PipelineInsightKind as ActionItemKind,
  type LegacyActionItem as ActionItem,
} from './pipelineInsights';
```

If TypeScript reports that older `ActionItemTarget` or `ActionItemSummary` consumers still need the old exact types, keep the old file body temporarily and add only a new export for `PipelineInsight`. Do not break existing imports in this task.

- [ ] **Step 5: Run tests and build for the model change**

Run:

```powershell
npm.cmd test -- pipelineInsights.test.ts
npm.cmd run build
```

Expected: tests pass and build succeeds. If build fails due to type compatibility with old `ActionItem` imports, keep old `actionItems.ts` intact and migrate consumers in later tasks.

- [ ] **Step 6: Commit Task 1**

```powershell
git add web/src/lib/pipelineInsights.ts web/src/lib/pipelineInsights.test.ts web/src/lib/actionItems.ts
git commit -m "feat: AI add pipeline insight rules"
```

---

### Task 2: Dashboard Insight Summary

**Files:**
- Modify: `web/src/features/dashboard/DashboardView.tsx`
- Modify: `web/src/features/dashboard/widgets/CommandCenter.tsx`
- Modify: `web/src/features/dashboard/widgets/ActionQueue.tsx`
- Modify: `web/src/features/dashboard/widgets/WeeklyRhythm.tsx`
- Modify: `web/src/features/dashboard/dashboard.module.css`

- [ ] **Step 1: Write or extend tests for summary helpers**

Extend `web/src/lib/pipelineInsights.test.ts`:

```ts
import { summarizePipelineHealth } from './pipelineInsights';

it('summarizes health from P0 and P1 insight counts', () => {
  const insights = derivePipelineInsights({
    apps: [app({ status: 'offer' })],
    events: [],
    offers: [offer({ deadline: '2026-07-04' })],
    now,
  });

  const health = summarizePipelineHealth([app({ status: 'offer' })], insights, 6);
  expect(health.score).toBeLessThan(100);
  expect(health.label).toBe('watch');
  expect(health.weeklyTarget).toBe(6);
});
```

- [ ] **Step 2: Run the focused test**

```powershell
npm.cmd test -- pipelineInsights.test.ts
```

Expected: pass if Task 1 is complete.

- [ ] **Step 3: Update `DashboardView` to derive insights and health**

In `web/src/features/dashboard/DashboardView.tsx`, import:

```ts
import { derivePipelineInsights, summarizePipelineHealth, type PipelineInsight } from '@/lib/pipelineInsights';
```

Replace the `actions` and `actionSummary` memo blocks with:

```ts
const insights = useMemo(
  () => derivePipelineInsights({ apps, events, offers, practiceStats: practiceStatsQ.data, now }),
  [apps, events, offers, practiceStatsQ.data, now],
);
const pipelineHealth = useMemo(
  () => summarizePipelineHealth(apps, insights),
  [apps, insights],
);
```

Update `handleAction`:

```ts
const handleAction = (item: PipelineInsight) => {
  if (item.target === 'board' && item.appId) {
    onOpenDetailById(item.appId);
    return;
  }
  onNavigate(item.target);
};
```

Update `CommandCenter` props:

```tsx
<CommandCenter
  items={insights}
  health={pipelineHealth}
  kpis={kpis}
  onAction={handleAction}
  onAddApplication={onAddApplication}
  onOpenQuestions={() => onNavigate('questions')}
  onSeeAll={() => onNavigate('reminders')}
/>
```

- [ ] **Step 4: Update `CommandCenter` props and copy**

In `web/src/features/dashboard/widgets/CommandCenter.tsx`, replace `ActionItem`/`ActionItemSummary` imports with:

```ts
import type { PipelineHealth, PipelineInsight } from '@/lib/pipelineInsights';
```

Change props:

```ts
interface Props {
  items: PipelineInsight[];
  health: PipelineHealth;
  kpis: Kpis;
  onAction: (item: PipelineInsight) => void;
  onAddApplication: () => void;
  onOpenQuestions: () => void;
  onSeeAll: () => void;
}
```

Change header text:

```tsx
<div className={styles.commandEyebrow}>Pipeline Intelligence</div>
<h2 id="command-center-title" className={styles.commandTitle}>
  Today has {items.length} recommended action{items.length === 1 ? '' : 's'}
</h2>
<p className={styles.commandSubtitle}>
  Ranked by deadline, pipeline risk, and preparation leverage. Each recommendation explains why it matters.
</p>
```

Replace `ActionSummary` usage with a compact health block:

```tsx
<div className={styles.pipelineHealthStrip}>
  <div>
    <span className={styles.kpiLabel}>Health score</span>
    <strong className={`${styles.kpiValue} op-tnum`}>{health.score}</strong>
  </div>
  <div>
    <span className={styles.kpiLabel}>State</span>
    <strong className={styles.healthLabel}>{health.label}</strong>
  </div>
  <div>
    <span className={styles.kpiLabel}>Bottleneck</span>
    <strong className={styles.healthText}>{health.bottleneck}</strong>
  </div>
</div>
```

Pass `health` into `WeeklyRhythm`:

```tsx
<WeeklyRhythm health={health} kpis={kpis} />
```

- [ ] **Step 5: Update `ActionQueue` to render insight reason and impact**

In `web/src/features/dashboard/widgets/ActionQueue.tsx`, use:

```ts
import type { PipelineInsight } from '@/lib/pipelineInsights';
```

Change props and priority label:

```ts
interface Props {
  items: PipelineInsight[];
  onAction: (item: PipelineInsight) => void;
  onAddApplication: () => void;
  onOpenQuestions: () => void;
  onSeeAll: () => void;
}

const PRIORITY_LABEL: Record<PipelineInsight['priority'], string> = {
  p0: 'P0',
  p1: 'P1',
  p2: 'P2',
};
```

Render detail:

```tsx
<span className={styles.actionDetail}>{item.reason}</span>
```

Keep the empty state, but change the text to:

```tsx
<div className={styles.actionEmptyTitle}>No urgent pipeline action right now</div>
<div className={styles.actionEmptyText}>
  Keep momentum by adding applications, practicing due questions, or writing a fresh interview retrospective.
</div>
```

- [ ] **Step 6: Update `WeeklyRhythm` to use health**

In `web/src/features/dashboard/widgets/WeeklyRhythm.tsx`, change props to accept `health: PipelineHealth` and show:

```tsx
<div className={styles.cardTitle}>Weekly rhythm</div>
<div className={styles.rhythmTrack}>
  <div
    className={styles.rhythmBar}
    style={{ width: `${Math.min(100, (health.weeklyApplications / health.weeklyTarget) * 100)}%` }}
  />
</div>
<div className={styles.rhythmMeta}>
  <span className="op-tnum">{health.weeklyApplications}/{health.weeklyTarget} applications</span>
  <span>{health.label}</span>
</div>
<p className={styles.rhythmText}>
  Pipeline health combines urgent deadlines, stale applications, and weekly top-of-funnel rhythm.
</p>
```

- [ ] **Step 7: Add CSS for health strip**

Append to `web/src/features/dashboard/dashboard.module.css`:

```css
.pipelineHealthStrip {
  display: grid;
  grid-template-columns: 120px 120px minmax(0, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}

.pipelineHealthStrip > div {
  min-width: 0;
  border-radius: 16px;
  padding: 12px;
  background: var(--op-layout-bg);
  box-shadow: inset 0 0 0 1px var(--op-border);
}

.healthLabel,
.healthText {
  display: block;
  margin-top: 3px;
  color: var(--op-ink);
  font-size: 14px;
  line-height: 1.35;
}

.healthLabel {
  text-transform: capitalize;
}

@media (max-width: 700px) {
  .pipelineHealthStrip {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 8: Run verification**

```powershell
npm.cmd test
npm.cmd run build
```

Expected: Vitest passes and Vite build succeeds.

- [ ] **Step 9: Commit Task 2**

```powershell
git add web/src/lib/pipelineInsights.test.ts web/src/features/dashboard/DashboardView.tsx web/src/features/dashboard/widgets/CommandCenter.tsx web/src/features/dashboard/widgets/ActionQueue.tsx web/src/features/dashboard/widgets/WeeklyRhythm.tsx web/src/features/dashboard/dashboard.module.css
git commit -m "feat: AI upgrade dashboard pipeline insights"
```

---

### Task 3: Shared Action Detail Drawer

**Files:**
- Create: `web/src/features/pipeline/ActionDetailDrawer.tsx`
- Create: `web/src/features/pipeline/pipeline.module.css`
- Modify: `web/src/features/dashboard/DashboardView.tsx`
- Modify: `web/src/features/dashboard/widgets/ActionQueue.tsx`

- [ ] **Step 1: Create the drawer component**

Create `web/src/features/pipeline/ActionDetailDrawer.tsx`:

```tsx
import { Button, Drawer, List, Space, Tag, Typography } from 'antd';
import type { PipelineInsight } from '@/lib/pipelineInsights';
import styles from './pipeline.module.css';

const { Paragraph, Text, Title } = Typography;

const PRIORITY_COLOR: Record<PipelineInsight['priority'], string> = {
  p0: 'red',
  p1: 'orange',
  p2: 'blue',
};

interface Props {
  insight: PipelineInsight | null;
  open: boolean;
  onClose: () => void;
  onRunAction: (insight: PipelineInsight, actionId: string) => void;
}

export default function ActionDetailDrawer({ insight, open, onClose, onRunAction }: Props) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      destroyOnClose
      title={insight ? (
        <Space>
          <Tag color={PRIORITY_COLOR[insight.priority]}>{insight.priority.toUpperCase()}</Tag>
          <span>{insight.title}</span>
        </Space>
      ) : 'Pipeline action'}
    >
      {!insight ? null : (
        <div className={styles.drawerBody}>
          <section className={styles.section}>
            <Title level={5}>Why this appears</Title>
            <Paragraph>{insight.reason}</Paragraph>
            <List
              size="small"
              dataSource={insight.evidence}
              renderItem={(item) => <List.Item><Text type="secondary">{item}</Text></List.Item>}
            />
          </section>

          <section className={styles.section}>
            <Title level={5}>Impact</Title>
            <Paragraph>{insight.impact}</Paragraph>
          </section>

          <section className={styles.section}>
            <Title level={5}>Recommended next step</Title>
            <Button type="primary" onClick={() => onRunAction(insight, insight.primaryAction.id)}>
              {insight.primaryAction.label}
            </Button>
            {insight.secondaryActions.length > 0 && (
              <div className={styles.secondaryActions}>
                {insight.secondaryActions.map((action) => (
                  <Button key={action.id} onClick={() => onRunAction(insight, action.id)}>
                    {action.label}
                  </Button>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 2: Create drawer CSS**

Create `web/src/features/pipeline/pipeline.module.css`:

```css
.drawerBody {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.section {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--op-border);
}

.section:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.secondaryActions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.secondaryActions :global(.ant-btn),
.section :global(.ant-btn) {
  min-height: 40px;
}
```

- [ ] **Step 3: Wire drawer into `DashboardView`**

In `DashboardView.tsx`, add:

```ts
import ActionDetailDrawer from '@/features/pipeline/ActionDetailDrawer';
```

Add state:

```ts
const [selectedInsight, setSelectedInsight] = useState<PipelineInsight | null>(null);
```

Change `handleAction`:

```ts
const handleAction = (item: PipelineInsight) => {
  setSelectedInsight(item);
};

const runInsightAction = (item: PipelineInsight) => {
  if (item.target === 'board' && item.appId) {
    setSelectedInsight(null);
    onOpenDetailById(item.appId);
    return;
  }
  setSelectedInsight(null);
  onNavigate(item.target);
};
```

Render after dashboard content:

```tsx
<ActionDetailDrawer
  insight={selectedInsight}
  open={!!selectedInsight}
  onClose={() => setSelectedInsight(null)}
  onRunAction={(item) => runInsightAction(item)}
/>
```

- [ ] **Step 4: Run verification**

```powershell
npm.cmd run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 5: Commit Task 3**

```powershell
git add web/src/features/pipeline/ActionDetailDrawer.tsx web/src/features/pipeline/pipeline.module.css web/src/features/dashboard/DashboardView.tsx
git commit -m "feat: AI add pipeline action detail drawer"
```

---

### Task 4: Reminders Action Center

**Files:**
- Modify: `web/src/features/reminders/RemindersView.tsx`
- Modify: `web/src/features/reminders/reminders.module.css`

- [ ] **Step 1: Replace reminder derivation with pipeline insights**

In `RemindersView.tsx`, import:

```ts
import { derivePipelineInsights, type PipelineInsight, type PipelinePriority, type PipelineInsightKind } from '@/lib/pipelineInsights';
import ActionDetailDrawer from '@/features/pipeline/ActionDetailDrawer';
import { Input, Select } from 'antd';
```

Use groups:

```ts
const GROUPS: { key: PipelinePriority; label: string }[] = [
  { key: 'p0', label: 'Today urgent' },
  { key: 'p1', label: 'This week focus' },
  { key: 'p2', label: 'Follow-up queue' },
];
```

Add local state:

```ts
const [selectedInsight, setSelectedInsight] = useState<PipelineInsight | null>(null);
const [kind, setKind] = useState<PipelineInsightKind | 'all'>('all');
const [keyword, setKeyword] = useState('');
```

Replace `actions` derivation:

```ts
const insights = useMemo(
  () => derivePipelineInsights({ apps, events, offers, practiceStats: practiceStatsQ.data, now }),
  [apps, events, offers, practiceStatsQ.data, now],
);

const filteredInsights = useMemo(() => {
  const q = keyword.trim().toLowerCase();
  return insights.filter((item) => {
    const kindMatch = kind === 'all' || item.kind === kind;
    const textMatch = !q || `${item.title} ${item.reason} ${item.evidence.join(' ')}`.toLowerCase().includes(q);
    return kindMatch && textMatch;
  });
}, [insights, kind, keyword]);
```

- [ ] **Step 2: Add filter controls and grouped cards**

Replace the component return body with:

```tsx
return (
  <div className={styles.wrap}>
    <div className={styles.toolbar}>
      <Input.Search
        allowClear
        aria-label="Search company, role, reason"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
      />
      <Select
        value={kind}
        onChange={setKind}
        style={{ minWidth: 220 }}
        options={[
          { value: 'all', label: 'All insight types' },
          { value: 'offer_deadline', label: 'Offer deadlines' },
          { value: 'interview_soon', label: 'Interview soon' },
          { value: 'stale_application', label: 'Stale applications' },
          { value: 'no_next_event', label: 'No next event' },
          { value: 'material_kit_incomplete', label: 'Material kits' },
          { value: 'question_due', label: 'Question practice' },
          { value: 'weekly_goal_gap', label: 'Weekly rhythm' },
        ]}
      />
    </div>

    {filteredInsights.length === 0 ? (
      <div className={styles.empty}>
        No matching pipeline actions. Add an application, practice due questions, or write a retrospective to keep momentum.
      </div>
    ) : (
      GROUPS.map(({ key, label }) => {
        const items = filteredInsights.filter((item) => item.priority === key);
        if (items.length === 0) return null;
        return (
          <div key={key} className={styles.group}>
            <div className={styles.groupTitle}>{label} ({items.length})</div>
            {items.map((item, i) => (
              <button
                key={item.id}
                type="button"
                className={styles.item}
                style={{ animationDelay: `${i * 40}ms` }}
                onClick={() => setSelectedInsight(item)}
              >
                <span className={`${styles.dot} ${styles[item.priority]}`} aria-hidden="true" />
                <span className={styles.body}>
                  <span className={styles.title}>{item.title}</span>
                  <span className={styles.detail}>{item.reason}</span>
                </span>
                <span className={styles.primaryAction}>{item.primaryAction.label}</span>
              </button>
            ))}
          </div>
        );
      })
    )}

    <ActionDetailDrawer
      insight={selectedInsight}
      open={!!selectedInsight}
      onClose={() => setSelectedInsight(null)}
      onRunAction={(item) => {
        setSelectedInsight(null);
        if (item.target === 'board' && item.appId) {
          onOpenDetailById(item.appId);
          return;
        }
        onNavigate(item.target);
      }}
    />
  </div>
);
```

- [ ] **Step 3: Add responsive toolbar styles**

Append to `web/src/features/reminders/reminders.module.css`:

```css
.toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto;
  gap: 10px;
  margin-bottom: 14px;
}

@media (max-width: 700px) {
  .toolbar {
    grid-template-columns: 1fr;
  }
}
```

Ensure `.item` has `min-height: 64px` and visible focus:

```css
.item:focus-visible {
  outline: 2px solid var(--op-primary);
  outline-offset: 2px;
}
```

- [ ] **Step 4: Run verification**

```powershell
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit Task 4**

```powershell
git add web/src/features/reminders/RemindersView.tsx web/src/features/reminders/reminders.module.css
git commit -m "feat: AI upgrade reminders action center"
```

---

### Task 5: Command Palette Pipeline Actions

**Files:**
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/CommandPalette.tsx`

- [ ] **Step 1: Extend command palette props**

In `CommandPalette.tsx`, import:

```ts
import type { PipelineInsight } from '@/lib/pipelineInsights';
```

Add props:

```ts
pipelineActions: PipelineInsight[];
onRunPipelineAction: (item: PipelineInsight) => void;
```

- [ ] **Step 2: Add action commands**

Inside the component, create:

```ts
const pipelineCommands: Command[] = pipelineActions.slice(0, 5).map((item) => ({
  key: `pipeline-${item.id}`,
  label: item.title,
  hint: `Pipeline 路 ${item.priority.toUpperCase()}`,
  run: () => {
    onRunPipelineAction(item);
    onClose();
  },
}));
```

Include these in `items` before generic navigation:

```ts
const items = [...appMatches, ...pipelineCommands, ...actionMatches];
```

Add verb actions to `actions`:

```ts
{ key: 'verb-follow-up', label: 'Follow up stale applications', hint: 'Pipeline', run: () => { onNavigate('reminders'); onClose(); } },
{ key: 'verb-prepare', label: 'Prepare upcoming interviews', hint: 'Pipeline', run: () => { onNavigate('reminders'); onClose(); } },
{ key: 'verb-review-week', label: 'Review this week strategy', hint: 'Pipeline', run: () => { onNavigate('dashboard'); onClose(); } },
```

- [ ] **Step 3: Pass pipeline actions from `AppShell`**

In `AppShell.tsx`, import:

```ts
import { derivePipelineInsights, toLegacyActionItems, type PipelineInsight } from '@/lib/pipelineInsights';
```

Replace old `actions` memo if Task 1 compatibility allows:

```ts
const pipelineActions = useMemo(
  () => derivePipelineInsights({ apps, events: evs, offers: ofrs, practiceStats, now }),
  [apps, evs, ofrs, practiceStats, now],
);
const actions = useMemo(() => toLegacyActionItems(pipelineActions), [pipelineActions]);
```

Add runner:

```ts
const runPipelineAction = (item: PipelineInsight) => {
  if (item.target === 'board' && item.appId) {
    goDetailById(item.appId);
    return;
  }
  setView(item.target);
};
```

Pass props:

```tsx
<CommandPalette
  ...
  pipelineActions={pipelineActions}
  onRunPipelineAction={runPipelineAction}
/>
```

- [ ] **Step 4: Run verification**

```powershell
npm.cmd run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit Task 5**

```powershell
git add web/src/layout/AppShell.tsx web/src/layout/CommandPalette.tsx
git commit -m "feat: AI add pipeline actions to command palette"
```

---

### Task 6: Route-Level Lazy Loading And Responsive Polish

**Files:**
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/Sidebar.tsx`
- Modify: `web/src/theme/tokens.css`

- [ ] **Step 1: Convert major view imports to lazy imports**

In `AppShell.tsx`, change imports:

```ts
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
```

Replace static imports for heavy views:

```ts
const KanbanBoard = lazy(() => import('@/components/KanbanBoard'));
const CalendarView = lazy(() => import('@/components/CalendarView'));
const ReviewManagementView = lazy(() => import('@/components/ReviewManagementView'));
const KnowledgeBaseView = lazy(() => import('@/components/KnowledgeBaseView'));
const QuestionBankView = lazy(() => import('@/components/QuestionBankView'));
const OfferCenterView = lazy(() => import('@/components/OfferCenterView'));
const DashboardView = lazy(() => import('@/features/dashboard/DashboardView'));
const RemindersView = lazy(() => import('@/features/reminders/RemindersView'));
const MockStudioView = lazy(() => import('@/components/MockStudio/MockStudioView'));
const ResumeLibraryView = lazy(() => import('@/components/ResumeLibraryView'));
```

Keep modal/drawer imports static if they are needed globally, unless build output still shows a large main chunk.

- [ ] **Step 2: Wrap view rendering with Suspense**

Wrap the `op-view-enter` view block:

```tsx
<Suspense fallback={<div style={{ textAlign: 'center', padding: 48 }}><Spin size="large" /></div>}>
  <div className="op-view-enter" key={view}>
    {/* existing view switches */}
  </div>
</Suspense>
```

- [ ] **Step 3: Add mobile-safe layout guard**

In `tokens.css`, add:

```css
* {
  box-sizing: border-box;
}

button,
[role="button"],
.ant-btn {
  touch-action: manipulation;
}
```

Do not add broad animation or color resets.

- [ ] **Step 4: Run build and compare chunking**

```powershell
npm.cmd run build
```

Expected: build succeeds and output contains multiple JS chunks. The main chunk should be lower than the previous approximately `1,741.96 kB` main bundle. Record the new largest chunk in the task notes or commit body.

- [ ] **Step 5: Commit Task 6**

```powershell
git add web/src/layout/AppShell.tsx web/src/theme/tokens.css
git commit -m "perf: AI lazy load major web views"
```

---

### Task 7: Final Verification And Browser QA

**Files:**
- No planned source edits unless verification exposes defects.

- [ ] **Step 1: Run full frontend tests**

```powershell
npm.cmd test
```

Expected: all Vitest files pass.

- [ ] **Step 2: Run production build**

```powershell
npm.cmd run build
```

Expected: TypeScript build and Vite build both succeed.

- [ ] **Step 3: Run backend tests**

```powershell
go test ./...
```

Expected: all Go packages pass.

- [ ] **Step 4: Start the local app**

Use the project鈥檚 existing server command. If `oc` is not built:

```powershell
go run ./cmd/oc start
```

Expected: local server starts on the configured port, usually `http://localhost:8080`.

- [ ] **Step 5: Browser check dashboard**

Open `http://localhost:8080`.

Verify:

- Dashboard loads without a blank screen.
- Pipeline Intelligence header is visible.
- Health score is visible and uses aligned numeric display.
- Top actions either show real actions or the empty state.
- Clicking a top action opens `ActionDetailDrawer`.

- [ ] **Step 6: Browser check reminders**

Navigate to Reminders.

Verify:

- P0/P1/P2 groups render when matching actions exist.
- Search filter narrows actions.
- Kind filter works.
- Clicking an action opens the same detail drawer.
- Empty state remains useful when no actions match.

- [ ] **Step 7: Browser check command palette**

Press `Ctrl+K`.

Verify:

- Application search still works.
- Pipeline actions appear near the top.
- Verb searches such as `follow`, `prepare`, and `review` produce useful commands.

- [ ] **Step 8: Browser check mobile width**

Set viewport to 375px wide.

Verify:

- No horizontal scroll.
- Dashboard health strip stacks vertically.
- Reminders toolbar stacks vertically.
- Buttons and action rows remain tappable.

- [ ] **Step 9: Commit any verification fixes**

If fixes were required:

```powershell
git add <changed-files>
git commit -m "fix: AI polish pipeline intelligence verification"
```

If no fixes were required, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage: tasks cover Pipeline Diagnostics, Action Detail Drawer, Weekly Strategy Review surface, Reminders action center, Command Palette, lazy loading, accessibility, and verification.
- Red-flag scan: every step names concrete files, commands, and code; no deferred work markers remain.
- Scope control: no database changes, no external scraping, no new UI framework, no automatic AI calls.
- Type consistency: the plan consistently uses `PipelineInsight`, `ActionCommand`, `PipelinePriority`, `PipelineInsightKind`, and `PipelineHealth`.
- Commit discipline: each task ends with a conventional commit matching the required `AI` prefix pattern.
