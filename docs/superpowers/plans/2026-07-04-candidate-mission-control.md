# Candidate Mission Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Candidate Mission Control as the dashboard's first-screen operating console for weekly goals, today's actions, application readiness, and focused next steps.

**Architecture:** Keep Mission Control local-first and frontend-derived. Add a focused `missionControl` library that composes existing applications, events, offers, material kits, practice stats, and `PipelineInsight` output; then render new dashboard widgets that link into existing pages and drawers rather than duplicating editors.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, React Query, Ant Design, CSS Modules, dayjs, Go backend verification.

---

## File Structure

- Create: `web/src/lib/missionControl.ts`
  - Deterministic derivation helpers for metrics, action groups, readiness, focus summary, and headline.
- Create: `web/src/lib/missionControl.test.ts`
  - Unit tests for weekly metrics, action grouping, readiness classification, empty/null inputs, and headline selection.
- Create: `web/src/features/dashboard/widgets/MissionHeader.tsx`
  - Top mission summary with week range, health label, headline, and next action CTA.
- Create: `web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx`
  - Compact metric tiles with current/target/state/reason.
- Create: `web/src/features/dashboard/widgets/TodayActionPlan.tsx`
  - Grouped `PipelineInsight` action rows that open `ActionDetailDrawer` through `DashboardView`.
- Create: `web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx`
  - Readiness cards for active applications.
- Create: `web/src/features/dashboard/widgets/FocusWorkspace.tsx`
  - Context panel for the selected application with navigation into existing modules.
- Modify: `web/src/features/dashboard/DashboardView.tsx`
  - Fetch material kits for active apps, derive Mission Control summary, manage focus state, and place new widgets before existing analytics.
- Modify: `web/src/features/dashboard/dashboard.module.css`
  - Add Mission Control layout, responsive rules, focus states, hit-area sizing, and reduced-motion behavior.
- Modify: `web/src/theme/tokens.css`
  - Add action/info semantic color tokens.

## Shared Conventions

- Keep weekly application target at `6`.
- Keep follow-up target at `3` only when stale applications exist.
- Treat `applied`, `assessment`, `written_test`, `interview`, and `offer` as active statuses.
- Keep existing garbled Chinese copy unchanged unless a touched string must be newly introduced. New user-visible copy in this feature should be clear Simplified Chinese.
- Do not add new backend tables or APIs.
- Do not add animation, chart, or icon dependencies.
- Use Ant Design icons already installed through `@ant-design/icons`.
- Use `git add` and `git commit` as separate commands.

---

### Task 1: Mission Control Derivation Library

**Files:**
- Create: `web/src/lib/missionControl.ts`
- Test: `web/src/lib/missionControl.test.ts`

- [ ] **Step 1: Write failing derivation tests**

Create `web/src/lib/missionControl.test.ts` with these tests:

```ts
import { describe, expect, it } from 'vitest';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { Offer } from '@/types/offer';
import type { MaterialKitViewModel } from '@/types/materialKit';
import type { PracticeStats } from '@/types/question';
import type { PipelineInsight } from './pipelineInsights';
import {
  deriveMissionControl,
  groupMissionActions,
  selectDefaultFocusApplicationId,
} from './missionControl';

const now = dayjs('2026-07-04T09:00:00+08:00');

function app(patch: Partial<Application> & Pick<Application, 'id'>): Application {
  return {
    id: patch.id,
    company_name: patch.company_name ?? `Company ${patch.id}`,
    position_name: patch.position_name ?? 'Backend Engineer',
    job_url: patch.job_url ?? '',
    status: patch.status ?? 'applied',
    source: patch.source ?? 'manual',
    notes: patch.notes ?? '',
    applied_at: patch.applied_at ?? '2026-07-01',
    created_at: patch.created_at ?? '2026-07-01T09:00:00+08:00',
    updated_at: patch.updated_at ?? '2026-07-01T09:00:00+08:00',
  };
}

function event(patch: Partial<ScheduleEvent> & Pick<ScheduleEvent, 'id' | 'application_id'>): ScheduleEvent {
  return {
    id: patch.id,
    application_id: patch.application_id,
    event_type: patch.event_type ?? 'interview',
    round: patch.round ?? 1,
    scheduled_at: patch.scheduled_at ?? '2026-07-05T10:00:00+08:00',
    duration_minutes: patch.duration_minutes ?? 60,
    location: patch.location ?? '',
    notes: patch.notes ?? '',
    company_name: patch.company_name,
    position_name: patch.position_name,
    created_at: patch.created_at ?? '2026-07-01T09:00:00+08:00',
  };
}

function offer(patch: Partial<Offer> & Pick<Offer, 'id'>): Offer {
  return {
    id: patch.id,
    application_id: patch.application_id ?? 1,
    company_name: patch.company_name ?? 'Company 1',
    position_name: patch.position_name ?? 'Backend Engineer',
    base_salary: patch.base_salary ?? 30000,
    months: patch.months ?? 16,
    signing_bonus: patch.signing_bonus ?? 0,
    annual_bonus: patch.annual_bonus ?? 0,
    equity_value: patch.equity_value ?? 0,
    perks: patch.perks ?? '',
    location: patch.location ?? '',
    deadline: patch.deadline ?? '',
    status: patch.status ?? 'pending',
    notes: patch.notes ?? '',
    total_cash: patch.total_cash ?? 480000,
    created_at: patch.created_at ?? '2026-07-01T09:00:00+08:00',
    updated_at: patch.updated_at ?? '2026-07-01T09:00:00+08:00',
  };
}

function kit(applicationId: number, status: MaterialKitViewModel['status']): MaterialKitViewModel {
  return {
    id: applicationId,
    application_id: applicationId,
    jd_snapshot: '',
    status,
    content: {
      resume_advice: { summary: '', highlights: [], rewrite_bullets: [], gaps: [], notes: '' },
      messages: [],
      checklist: [],
    },
    created_at: '2026-07-01T09:00:00+08:00',
    updated_at: '2026-07-01T09:00:00+08:00',
  };
}

function insight(patch: Partial<PipelineInsight> & Pick<PipelineInsight, 'id' | 'kind'>): PipelineInsight {
  return {
    id: patch.id,
    kind: patch.kind,
    priority: patch.priority ?? 'p2',
    title: patch.title ?? patch.id,
    reason: patch.reason ?? 'reason',
    evidence: patch.evidence ?? ['evidence'],
    primaryAction: patch.primaryAction ?? { label: 'Open', target: 'board', appId: patch.appId },
    sortKey: patch.sortKey ?? 100,
    appId: patch.appId,
    offerId: patch.offerId,
    eventId: patch.eventId,
    questionCount: patch.questionCount,
  };
}

describe('deriveMissionControl', () => {
  it('builds weekly metrics with explicit target states', () => {
    const summary = deriveMissionControl({
      apps: [
        app({ id: 1, applied_at: '2026-07-01' }),
        app({ id: 2, applied_at: '2026-07-02' }),
      ],
      events: [event({ id: 1, application_id: 1 })],
      offers: [],
      materialKits: [kit(1, 'ready'), kit(2, 'draft')],
      practiceStats: { total: 12, due: 4, mastered: 3, practicing: 5, new: 4 } as PracticeStats,
      insights: [insight({ id: 'questions-due', kind: 'question_due', questionCount: 4 })],
      healthLabel: 'watch',
      weeklyTarget: 6,
      now,
    });

    expect(summary.metrics.find((metric) => metric.kind === 'applications')).toMatchObject({
      current: 2,
      target: 6,
      state: 'behind',
      targetView: 'board',
    });
    expect(summary.metrics.find((metric) => metric.kind === 'practice')).toMatchObject({
      current: 4,
      target: 1,
      state: 'watch',
      targetView: 'questions',
    });
    expect(summary.metrics.find((metric) => metric.kind === 'materials')).toMatchObject({
      current: 1,
      target: 2,
      state: 'watch',
      targetView: 'board',
    });
  });

  it('classifies readiness as blocked for imminent interviews without ready material', () => {
    const summary = deriveMissionControl({
      apps: [app({ id: 1, status: 'interview', company_name: 'ByteDance' })],
      events: [event({ id: 1, application_id: 1, scheduled_at: '2026-07-04T18:00:00+08:00' })],
      offers: [],
      materialKits: [kit(1, 'draft')],
      practiceStats: { total: 0, due: 0, mastered: 0, practicing: 0, new: 0 } as PracticeStats,
      insights: [],
      healthLabel: 'watch',
      weeklyTarget: 6,
      now,
    });

    expect(summary.readiness[0]).toMatchObject({
      applicationId: 1,
      companyName: 'ByteDance',
      readiness: 'blocked',
      materialStatus: 'draft',
      hasUpcomingEvent: true,
    });
    expect(summary.readiness[0].evidence.join(' ')).toContain('24 小时');
  });

  it('groups actions into urgent prepare and momentum buckets', () => {
    const groups = groupMissionActions([
      insight({ id: 'p0-offer', kind: 'offer_deadline', priority: 'p0' }),
      insight({ id: 'prepare', kind: 'interview_soon', priority: 'p1' }),
      insight({ id: 'momentum', kind: 'weekly_goal_gap', priority: 'p2' }),
    ]);

    expect(groups.urgent.map((item) => item.id)).toEqual(['p0-offer']);
    expect(groups.prepare.map((item) => item.id)).toEqual(['prepare']);
    expect(groups.momentum.map((item) => item.id)).toEqual(['momentum']);
  });

  it('selects a default focus application from urgent readiness before other active apps', () => {
    const focus = selectDefaultFocusApplicationId([
      {
        applicationId: 2,
        companyName: 'Ready Co',
        positionName: 'Backend',
        status: 'applied',
        readiness: 'ready',
        materialStatus: 'ready',
        hasUpcomingEvent: false,
        evidence: [],
      },
      {
        applicationId: 1,
        companyName: 'Blocked Co',
        positionName: 'Backend',
        status: 'interview',
        readiness: 'blocked',
        materialStatus: 'draft',
        hasUpcomingEvent: true,
        evidence: [],
      },
    ]);

    expect(focus).toBe(1);
  });

  it('handles null optional arrays and produces an empty-state headline', () => {
    const summary = deriveMissionControl({
      apps: null,
      events: null,
      offers: null,
      materialKits: null,
      practiceStats: null,
      insights: [],
      healthLabel: 'healthy',
      weeklyTarget: 6,
      now,
    });

    expect(summary.metrics.find((metric) => metric.kind === 'applications')).toMatchObject({
      current: 0,
      state: 'behind',
    });
    expect(summary.readiness).toEqual([]);
    expect(summary.headline).toContain('添加第一条投递');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
npm.cmd test -- missionControl.test.ts
```

Expected: FAIL with an import error similar to `Failed to resolve import "./missionControl"`.

- [ ] **Step 3: Implement `missionControl.ts`**

Create `web/src/lib/missionControl.ts`:

```ts
import dayjs, { type ConfigType } from 'dayjs';
import type { Application, ApplicationStatus } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { MaterialKitViewModel, MaterialKitStatus } from '@/types/materialKit';
import type { Offer } from '@/types/offer';
import type { PracticeStats } from '@/types/question';
import type { ViewMode } from '@/layout/AppShell';
import type { PipelineHealth, PipelineInsight, PipelineInsightKind } from './pipelineInsights';

export type MissionMetricKind =
  | 'applications'
  | 'followups'
  | 'interviews'
  | 'practice'
  | 'materials'
  | 'offers';

export type MissionMetricState = 'on_track' | 'watch' | 'behind' | 'blocked';
export type ApplicationReadinessState = 'ready' | 'watch' | 'blocked';
export type ReadinessMaterialStatus = MaterialKitStatus | 'missing' | 'unknown';

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
  readiness: ApplicationReadinessState;
  materialStatus: ReadinessMaterialStatus;
  hasUpcomingEvent: boolean;
  staleDays?: number;
  dueQuestionCount?: number;
  evidence: string[];
}

export interface MissionActionGroups {
  urgent: PipelineInsight[];
  prepare: PipelineInsight[];
  momentum: PipelineInsight[];
}

export interface MissionControlSummary {
  weekStart: string;
  weekEnd: string;
  headline: string;
  healthLabel: PipelineHealth['label'];
  metrics: MissionMetric[];
  actions: PipelineInsight[];
  actionGroups: MissionActionGroups;
  readiness: ApplicationReadiness[];
  focusApplicationId?: number;
}

interface DeriveMissionControlInput {
  apps: Application[] | null | undefined;
  events: ScheduleEvent[] | null | undefined;
  offers: Offer[] | null | undefined;
  materialKits?: MaterialKitViewModel[] | null;
  practiceStats?: PracticeStats | null;
  insights: PipelineInsight[];
  healthLabel: PipelineHealth['label'];
  weeklyTarget?: number;
  now?: ConfigType;
}

const ACTIVE_STATUSES: ApplicationStatus[] = ['applied', 'assessment', 'written_test', 'interview', 'offer'];
const WAITING_STATUSES: ApplicationStatus[] = ['applied', 'assessment', 'written_test'];
const PREPARE_KINDS: PipelineInsightKind[] = [
  'offer_deadline',
  'interview_soon',
  'material_kit_incomplete',
  'question_due',
];
const DEFAULT_WEEKLY_TARGET = 6;
const FOLLOWUP_TARGET = 3;

function parseDate(value?: string): dayjs.Dayjs | null {
  if (!value) return null;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed : null;
}

function isActiveApplication(app: Application): boolean {
  return ACTIVE_STATUSES.includes(app.status);
}

function isWaitingApplication(app: Application): boolean {
  return WAITING_STATUSES.includes(app.status);
}

function isReadyMaterial(status: ReadinessMaterialStatus): boolean {
  return status === 'ready' || status === 'submitted';
}

function stateForProgress(current: number, target: number): MissionMetricState {
  if (target <= 0) return 'on_track';
  if (current >= target) return 'on_track';
  if (current === 0) return 'behind';
  if (current / target >= 0.5) return 'watch';
  return 'behind';
}

function formatWeekDate(value: dayjs.Dayjs): string {
  return value.format('YYYY-MM-DD');
}

function getMaterialStatus(appId: number, materialKits: MaterialKitViewModel[] | null | undefined): ReadinessMaterialStatus {
  if (materialKits == null) return 'unknown';
  return materialKits.find((kit) => kit.application_id === appId)?.status ?? 'missing';
}

function getUpcomingEvents(appId: number, events: ScheduleEvent[], now: dayjs.Dayjs): ScheduleEvent[] {
  return events
    .filter((event) => event.application_id === appId)
    .filter((event) => {
      const scheduled = parseDate(event.scheduled_at);
      return Boolean(scheduled?.isAfter(now));
    })
    .sort((left, right) => dayjs(left.scheduled_at).valueOf() - dayjs(right.scheduled_at).valueOf());
}

function getStaleDays(app: Application, now: dayjs.Dayjs): number | undefined {
  if (!isWaitingApplication(app)) return undefined;
  const base = parseDate(app.updated_at || app.applied_at);
  if (!base) return undefined;
  const days = now.diff(base, 'day');
  return Number.isFinite(days) && days > 7 ? days : undefined;
}

function buildMetrics(
  apps: Application[],
  events: ScheduleEvent[],
  offers: Offer[],
  materialKits: MaterialKitViewModel[] | null | undefined,
  practiceStats: PracticeStats | null | undefined,
  weeklyTarget: number,
  now: dayjs.Dayjs,
): MissionMetric[] {
  const weekStart = now.startOf('week');
  const weekEnd = now.endOf('week');
  const activeApps = apps.filter(isActiveApplication);
  const weeklyApplications = apps.filter((app) => {
    const appliedAt = parseDate(app.applied_at);
    return Boolean(appliedAt && !appliedAt.isBefore(weekStart) && !appliedAt.isAfter(weekEnd));
  }).length;
  const staleCount = activeApps.filter((app) => (getStaleDays(app, now) ?? 0) > 7).length;
  const interviewsThisWeek = events.filter((event) => {
    const scheduled = parseDate(event.scheduled_at);
    return Boolean(scheduled && !scheduled.isBefore(weekStart) && !scheduled.isAfter(weekEnd));
  }).length;
  const dueQuestions = practiceStats?.due ?? 0;
  const readyMaterials =
    materialKits == null
      ? 0
      : activeApps.filter((app) => isReadyMaterial(getMaterialStatus(app.id, materialKits))).length;
  const pendingOffers = offers.filter((offer) => ['pending', 'negotiating'].includes(offer.status));
  const urgentOffers = pendingOffers.filter((offer) => {
    const deadline = parseDate(offer.deadline);
    return Boolean(deadline && deadline.diff(now, 'hour', true) >= 0 && deadline.diff(now, 'hour', true) <= 48);
  }).length;

  return [
    {
      kind: 'applications',
      label: '本周投递',
      current: weeklyApplications,
      target: weeklyTarget,
      state: stateForProgress(weeklyApplications, weeklyTarget),
      reason: `本周已新增 ${weeklyApplications} 个投递，目标 ${weeklyTarget} 个。`,
      targetView: 'board',
    },
    {
      kind: 'followups',
      label: '跟进节奏',
      current: staleCount,
      target: staleCount > 0 ? FOLLOWUP_TARGET : 0,
      state: staleCount === 0 ? 'on_track' : staleCount >= FOLLOWUP_TARGET ? 'blocked' : 'watch',
      reason: staleCount === 0 ? '暂无明显停滞的活跃投递。' : `${staleCount} 个活跃投递需要跟进。`,
      targetView: 'reminders',
    },
    {
      kind: 'interviews',
      label: '本周面试',
      current: interviewsThisWeek,
      state: interviewsThisWeek > 0 ? 'watch' : 'on_track',
      reason: interviewsThisWeek > 0 ? `本周有 ${interviewsThisWeek} 个面试或测评日程。` : '本周暂无已安排面试。',
      targetView: 'calendar',
    },
    {
      kind: 'practice',
      label: '刷题准备',
      current: dueQuestions,
      target: dueQuestions > 0 ? 1 : 0,
      state: dueQuestions >= 10 ? 'behind' : dueQuestions > 0 ? 'watch' : 'on_track',
      reason: dueQuestions > 0 ? `${dueQuestions} 道题到期需要复习。` : '暂无到期题目。',
      targetView: 'questions',
    },
    {
      kind: 'materials',
      label: '材料就绪',
      current: readyMaterials,
      target: activeApps.length,
      state:
        materialKits == null
          ? 'watch'
          : readyMaterials >= activeApps.length
            ? 'on_track'
            : readyMaterials === 0 && activeApps.length > 0
              ? 'behind'
              : 'watch',
      reason:
        materialKits == null
          ? '材料状态暂不可用。'
          : `${readyMaterials}/${activeApps.length} 个活跃投递材料已就绪。`,
      targetView: 'board',
    },
    {
      kind: 'offers',
      label: 'Offer 压力',
      current: urgentOffers,
      target: pendingOffers.length,
      state: urgentOffers > 0 ? 'blocked' : pendingOffers.length > 0 ? 'watch' : 'on_track',
      reason: urgentOffers > 0 ? `${urgentOffers} 个 Offer 截止期进入 48 小时内。` : '暂无 48 小时内截止的 Offer。',
      targetView: 'offers',
    },
  ];
}

function buildReadiness(
  apps: Application[],
  events: ScheduleEvent[],
  materialKits: MaterialKitViewModel[] | null | undefined,
  practiceStats: PracticeStats | null | undefined,
  now: dayjs.Dayjs,
): ApplicationReadiness[] {
  const dueQuestionCount = practiceStats?.due ?? 0;

  return apps
    .filter(isActiveApplication)
    .map((app) => {
      const materialStatus = getMaterialStatus(app.id, materialKits);
      const upcomingEvents = getUpcomingEvents(app.id, events, now);
      const nextEvent = upcomingEvents[0];
      const hoursToEvent = nextEvent ? dayjs(nextEvent.scheduled_at).diff(now, 'hour', true) : undefined;
      const staleDays = getStaleDays(app, now);
      const evidence: string[] = [];
      let readiness: ApplicationReadinessState = 'ready';

      if (nextEvent) evidence.push(`下一场日程：${dayjs(nextEvent.scheduled_at).format('MM-DD HH:mm')}`);
      if (materialStatus === 'unknown') evidence.push('材料状态暂不可用');
      else evidence.push(`材料状态：${materialStatus}`);
      if (staleDays) evidence.push(`已 ${staleDays} 天未更新`);
      if (dueQuestionCount > 0) evidence.push(`${dueQuestionCount} 道题到期`);

      if (hoursToEvent != null && hoursToEvent >= 0 && hoursToEvent <= 24 && !isReadyMaterial(materialStatus)) {
        readiness = 'blocked';
        evidence.push('24 小时内有日程但材料未就绪');
      } else if (
        staleDays ||
        (app.status === 'interview' && upcomingEvents.length === 0) ||
        materialStatus === 'draft' ||
        materialStatus === 'missing' ||
        dueQuestionCount > 0
      ) {
        readiness = 'watch';
      }

      return {
        applicationId: app.id,
        companyName: app.company_name,
        positionName: app.position_name,
        status: app.status,
        readiness,
        materialStatus,
        hasUpcomingEvent: upcomingEvents.length > 0,
        staleDays,
        dueQuestionCount,
        evidence,
      };
    })
    .sort((left, right) => {
      const rank: Record<ApplicationReadinessState, number> = { blocked: 0, watch: 1, ready: 2 };
      return rank[left.readiness] - rank[right.readiness] || left.applicationId - right.applicationId;
    });
}

export function groupMissionActions(insights: PipelineInsight[]): MissionActionGroups {
  return {
    urgent: insights.filter((item) => item.priority === 'p0'),
    prepare: insights.filter((item) => item.priority !== 'p0' && PREPARE_KINDS.includes(item.kind)),
    momentum: insights.filter((item) => item.priority !== 'p0' && !PREPARE_KINDS.includes(item.kind)),
  };
}

export function selectDefaultFocusApplicationId(readiness: ApplicationReadiness[]): number | undefined {
  return readiness[0]?.applicationId;
}

function buildHeadline(metrics: MissionMetric[], actions: PipelineInsight[], readiness: ApplicationReadiness[]): string {
  if (metrics.find((metric) => metric.kind === 'applications')?.current === 0 && readiness.length === 0) {
    return '添加第一条投递，OfferPilot 会开始组织你的求职节奏。';
  }

  const urgent = actions.find((item) => item.priority === 'p0');
  if (urgent) return `优先处理：${urgent.title}`;

  const blocked = readiness.find((item) => item.readiness === 'blocked');
  if (blocked) return `先解除 ${blocked.companyName} 的准备阻塞。`;

  const behind = metrics.find((metric) => metric.state === 'behind');
  if (behind) return `${behind.label}落后于本周目标。`;

  return '本周节奏稳定，保持跟进和准备即可。';
}

export function deriveMissionControl({
  apps,
  events,
  offers,
  materialKits,
  practiceStats,
  insights,
  healthLabel,
  weeklyTarget = DEFAULT_WEEKLY_TARGET,
  now = dayjs(),
}: DeriveMissionControlInput): MissionControlSummary {
  const current = dayjs(now);
  const safeApps = apps ?? [];
  const safeEvents = events ?? [];
  const safeOffers = offers ?? [];
  const weekStart = current.startOf('week');
  const weekEnd = current.endOf('week');
  const metrics = buildMetrics(safeApps, safeEvents, safeOffers, materialKits, practiceStats, weeklyTarget, current);
  const readiness = buildReadiness(safeApps, safeEvents, materialKits, practiceStats, current);
  const actionGroups = groupMissionActions(insights);

  return {
    weekStart: formatWeekDate(weekStart),
    weekEnd: formatWeekDate(weekEnd),
    headline: buildHeadline(metrics, insights, readiness),
    healthLabel,
    metrics,
    actions: insights,
    actionGroups,
    readiness,
    focusApplicationId: selectDefaultFocusApplicationId(readiness),
  };
}
```

- [ ] **Step 4: Run mission control tests**

Run:

```powershell
npm.cmd test -- missionControl.test.ts
```

Expected: PASS, 5 tests passing.

- [ ] **Step 5: Run all frontend tests**

Run:

```powershell
npm.cmd test
```

Expected: PASS, existing tests plus `missionControl.test.ts`.

- [ ] **Step 6: Commit derivation library**

Run:

```powershell
git add web/src/lib/missionControl.ts web/src/lib/missionControl.test.ts
git commit -m "feat: AI add mission control derivation"
```

Expected: commit succeeds.

---

### Task 2: Mission Header And Weekly Mission Panel

**Files:**
- Create: `web/src/features/dashboard/widgets/MissionHeader.tsx`
- Create: `web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx`
- Modify: `web/src/features/dashboard/dashboard.module.css`
- Modify: `web/src/theme/tokens.css`

- [ ] **Step 1: Add semantic action tokens**

Modify `web/src/theme/tokens.css` inside `:root` after `--op-accent`:

```css
  --op-action: #f97316;
  --op-action-strong: #ea580c;
  --op-action-soft: #fff4e8;
  --op-info: #0d9488;
  --op-info-soft: #ecfdf5;
```

Modify `:root[data-theme="dark"]` after `--op-primary-strong`:

```css
  --op-action: #fb923c;
  --op-action-strong: #fdba74;
  --op-action-soft: #3a2416;
  --op-info: #5eead4;
  --op-info-soft: #173a35;
```

- [ ] **Step 2: Create `MissionHeader.tsx`**

Create `web/src/features/dashboard/widgets/MissionHeader.tsx`:

```tsx
import { Button, Tag } from 'antd';
import { ArrowRightOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { formatPipelineHealthLabel, type PipelineInsight } from '@/lib/pipelineInsights';
import type { MissionControlSummary } from '@/lib/missionControl';
import styles from '../dashboard.module.css';

interface Props {
  summary: MissionControlSummary;
  nextAction?: PipelineInsight;
  onRunAction: (item: PipelineInsight) => void;
  onAddApplication: () => void;
}

export default function MissionHeader({ summary, nextAction, onRunAction, onAddApplication }: Props) {
  const healthColor = summary.healthLabel === 'critical' ? 'red' : summary.healthLabel === 'watch' ? 'orange' : 'green';

  return (
    <section className={styles.missionHeader} aria-labelledby="mission-control-title">
      <div className={styles.missionHeaderText}>
        <div className={styles.commandEyebrow}>Mission Control</div>
        <h1 id="mission-control-title" className={styles.missionTitle}>
          本周求职作战台
        </h1>
        <p className={styles.missionHeadline}>{summary.headline}</p>
        <div className={styles.missionMeta}>
          <span className="op-tnum">
            {summary.weekStart} - {summary.weekEnd}
          </span>
          <Tag color={healthColor}>{formatPipelineHealthLabel(summary.healthLabel)}</Tag>
        </div>
      </div>

      <div className={styles.missionHeaderAction}>
        {nextAction ? (
          <Button
            type="primary"
            size="large"
            className={nextAction.priority === 'p0' ? styles.actionCta : undefined}
            icon={<ThunderboltOutlined />}
            onClick={() => onRunAction(nextAction)}
          >
            {nextAction.primaryAction.label}
            <ArrowRightOutlined />
          </Button>
        ) : (
          <Button type="primary" size="large" onClick={onAddApplication}>
            添加投递
            <ArrowRightOutlined />
          </Button>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: Create `WeeklyMissionPanel.tsx`**

Create `web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx`:

```tsx
import {
  CalendarOutlined,
  CheckCircleOutlined,
  FileDoneOutlined,
  FlagOutlined,
  ReadOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import type { MissionMetric, MissionMetricKind, MissionMetricState } from '@/lib/missionControl';
import type { ViewMode } from '@/layout/AppShell';
import styles from '../dashboard.module.css';

interface Props {
  metrics: MissionMetric[];
  onNavigate: (view: ViewMode) => void;
}

const ICONS: Record<MissionMetricKind, ReactNode> = {
  applications: <FlagOutlined />,
  followups: <CheckCircleOutlined />,
  interviews: <CalendarOutlined />,
  practice: <ReadOutlined />,
  materials: <FileDoneOutlined />,
  offers: <TrophyOutlined />,
};

const STATE_LABELS: Record<MissionMetricState, string> = {
  on_track: '正常',
  watch: '关注',
  behind: '落后',
  blocked: '阻塞',
};

function formatValue(metric: MissionMetric): string {
  if (metric.target == null || metric.target === 0) return `${metric.current}`;
  return `${metric.current}/${metric.target}`;
}

export default function WeeklyMissionPanel({ metrics, onNavigate }: Props) {
  return (
    <section className={styles.weeklyMissionPanel} aria-label="本周目标">
      {metrics.map((metric) => (
        <button
          key={metric.kind}
          type="button"
          className={`${styles.missionMetric} ${styles[`metric-${metric.state}`]}`}
          onClick={() => onNavigate(metric.targetView)}
        >
          <span className={styles.metricIcon} aria-hidden="true">
            {ICONS[metric.kind]}
          </span>
          <span className={styles.metricBody}>
            <span className={styles.metricLabel}>{metric.label}</span>
            <span className={`${styles.metricValue} op-tnum`}>{formatValue(metric)}</span>
            <span className={styles.metricReason}>{metric.reason}</span>
          </span>
          <span className={styles.metricState}>{STATE_LABELS[metric.state]}</span>
        </button>
      ))}
    </section>
  );
}
```

- [ ] **Step 4: Add CSS for header and metrics**

Append to `web/src/features/dashboard/dashboard.module.css`:

```css
.missionHeader {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  padding: 20px;
  border-radius: 22px;
  background:
    linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(13, 148, 136, 0.08)),
    var(--op-surface);
  box-shadow: var(--op-shadow-md);
}

.missionHeaderText {
  min-width: 0;
}

.missionTitle {
  margin: 5px 0 6px;
  color: var(--op-ink);
  font-size: 28px;
  line-height: 1.15;
  text-wrap: balance;
}

.missionHeadline {
  margin: 0;
  color: var(--op-muted-strong);
  font-size: 14px;
  line-height: 1.7;
  text-wrap: pretty;
}

.missionMeta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: var(--op-muted-strong);
  font-size: 12px;
}

.missionHeaderAction {
  flex: 0 0 auto;
}

.actionCta.actionCta {
  background: var(--op-action);
  border-color: var(--op-action);
  color: #111827;
}

.weeklyMissionPanel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.missionMetric {
  min-height: 112px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 14px;
  border: none;
  border-radius: 18px;
  background: var(--op-surface);
  color: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow:
    0 0 0 1px rgba(31, 29, 58, 0.06),
    0 2px 10px rgba(99, 102, 241, 0.08);
  transition-property: transform, box-shadow, background-color;
  transition-duration: 0.18s;
  transition-timing-function: var(--op-ease);
}

.missionMetric:hover,
.missionMetric:focus-visible {
  outline: none;
  transform: translateY(-1px);
  box-shadow: var(--op-shadow-lg);
}

.missionMetric:active {
  transform: scale(0.96);
}

.metricIcon {
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: var(--op-layout-bg);
  color: var(--op-primary-strong);
  font-size: 18px;
}

.metricBody {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metricLabel {
  color: var(--op-muted-strong);
  font-size: 12px;
  font-weight: 700;
}

.metricValue {
  color: var(--op-ink);
  font-size: 24px;
  line-height: 1;
  font-weight: 800;
}

.metricReason {
  color: var(--op-muted-strong);
  font-size: 12px;
  line-height: 1.5;
  text-wrap: pretty;
}

.metricState {
  min-width: 42px;
  padding: 4px 7px;
  border-radius: 999px;
  color: var(--op-muted-strong);
  background: var(--op-layout-bg);
  font-size: 12px;
  font-weight: 700;
  text-align: center;
}

.metric-blocked .metricState {
  background: rgba(239, 68, 68, 0.14);
  color: var(--op-error);
}

.metric-behind .metricState {
  background: var(--op-action-soft);
  color: var(--op-action-strong);
}

.metric-watch .metricState {
  background: rgba(217, 119, 6, 0.14);
  color: var(--op-warning-strong);
}

.metric-on_track .metricState {
  background: var(--op-info-soft);
  color: var(--op-info);
}
```

- [ ] **Step 5: Run build to catch component and CSS module errors**

Run:

```powershell
npm.cmd run build
```

Expected: PASS. The build may still report existing chunk-size warnings.

- [ ] **Step 6: Commit header and metrics**

Run:

```powershell
git add web/src/features/dashboard/widgets/MissionHeader.tsx web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx web/src/features/dashboard/dashboard.module.css web/src/theme/tokens.css
git commit -m "feat: AI add mission header metrics"
```

Expected: commit succeeds.

---

### Task 3: Today Action Plan Widget

**Files:**
- Create: `web/src/features/dashboard/widgets/TodayActionPlan.tsx`
- Modify: `web/src/features/dashboard/dashboard.module.css`

- [ ] **Step 1: Create `TodayActionPlan.tsx`**

Create `web/src/features/dashboard/widgets/TodayActionPlan.tsx`:

```tsx
import { Empty, Tag } from 'antd';
import { FireOutlined, FlagOutlined, ToolOutlined } from '@ant-design/icons';
import type { MissionActionGroups } from '@/lib/missionControl';
import type { PipelineInsight } from '@/lib/pipelineInsights';
import styles from '../dashboard.module.css';

interface Props {
  groups: MissionActionGroups;
  onAction: (item: PipelineInsight) => void;
  onSeeAll: () => void;
}

const GROUP_META = [
  { key: 'urgent', title: '紧急处理', icon: <FireOutlined />, tag: 'P0' },
  { key: 'prepare', title: '准备推进', icon: <ToolOutlined />, tag: '准备' },
  { key: 'momentum', title: '保持节奏', icon: <FlagOutlined />, tag: '节奏' },
] as const;

function priorityLabel(item: PipelineInsight): string {
  return item.priority.toUpperCase();
}

function evidenceHint(item: PipelineInsight): string {
  return item.evidence[0] ?? item.reason;
}

export default function TodayActionPlan({ groups, onAction, onSeeAll }: Props) {
  const total = groups.urgent.length + groups.prepare.length + groups.momentum.length;

  return (
    <section className={styles.todayActionPlan} aria-labelledby="today-action-plan-title">
      <div className={styles.sectionHeaderLine}>
        <div>
          <div className={styles.commandEyebrow}>Today</div>
          <h2 id="today-action-plan-title" className={styles.sectionHeading}>
            今日行动计划
          </h2>
        </div>
        <button type="button" className={styles.textButton} onClick={onSeeAll}>
          查看全部
        </button>
      </div>

      {total === 0 ? (
        <Empty
          className={styles.compactEmpty}
          description="暂无需要立即处理的行动。可以新增投递、整理材料，或进行一轮题目复习。"
        />
      ) : (
        <div className={styles.actionPlanGroups}>
          {GROUP_META.map((meta) => {
            const items = groups[meta.key];
            if (items.length === 0) return null;
            return (
              <div key={meta.key} className={styles.actionPlanGroup}>
                <div className={styles.actionPlanGroupTitle}>
                  <span aria-hidden="true">{meta.icon}</span>
                  <span>{meta.title}</span>
                  <Tag>{meta.tag}</Tag>
                </div>
                <div className={styles.actionPlanList}>
                  {items.slice(0, 4).map((item, index) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`${styles.planActionRow} ${styles[item.priority]}`}
                      style={{ animationDelay: `${index * 40}ms` }}
                      onClick={() => onAction(item)}
                    >
                      <span className={`${styles.planPriority} op-tnum`}>{priorityLabel(item)}</span>
                      <span className={styles.planActionBody}>
                        <span className={styles.planActionTitle}>{item.title}</span>
                        <span className={styles.planActionReason}>{item.reason}</span>
                        <span className={styles.planActionEvidence}>{evidenceHint(item)}</span>
                      </span>
                      <span className={styles.planActionCta}>{item.primaryAction.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Add action plan CSS**

Append to `web/src/features/dashboard/dashboard.module.css`:

```css
.todayActionPlan {
  min-width: 0;
  padding: 18px;
  border-radius: 20px;
  background: var(--op-surface);
  box-shadow: var(--op-shadow-md);
}

.sectionHeaderLine {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}

.sectionHeading {
  margin: 4px 0 0;
  color: var(--op-ink);
  font-size: 18px;
  line-height: 1.25;
  text-wrap: balance;
}

.textButton {
  min-height: 40px;
  border: none;
  padding: 0 8px;
  background: transparent;
  color: var(--op-primary-strong);
  font-weight: 700;
  cursor: pointer;
  transition-property: color, opacity;
  transition-duration: 0.18s;
  transition-timing-function: var(--op-ease);
}

.textButton:hover,
.textButton:focus-visible {
  color: var(--op-primary);
  outline: none;
}

.compactEmpty {
  padding: 24px 8px;
}

.actionPlanGroups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.actionPlanGroupTitle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--op-ink);
  font-size: 13px;
  font-weight: 800;
}

.actionPlanList {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.planActionRow {
  width: 100%;
  min-height: 76px;
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  border: none;
  border-radius: 16px;
  padding: 12px;
  background: var(--op-layout-bg);
  color: inherit;
  text-align: left;
  cursor: pointer;
  animation: actionIn 0.24s var(--op-ease) both;
  box-shadow: 0 0 0 1px rgba(31, 29, 58, 0.05);
  transition-property: transform, box-shadow, background-color;
  transition-duration: 0.18s;
  transition-timing-function: var(--op-ease);
}

.planActionRow:hover,
.planActionRow:focus-visible {
  outline: none;
  transform: translateY(-1px);
  background: var(--op-action-soft);
  box-shadow: var(--op-shadow-lg);
}

.planActionRow:active {
  transform: scale(0.96);
}

.planPriority {
  width: 42px;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 900;
}

.p0 .planPriority {
  background: var(--op-error);
  color: var(--op-on-danger);
}

.p1 .planPriority {
  background: var(--op-warning);
  color: var(--op-on-warning);
}

.p2 .planPriority {
  background: var(--op-primary);
  color: var(--op-on-primary);
}

.planActionBody {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.planActionTitle {
  color: var(--op-ink);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.4;
}

.planActionReason,
.planActionEvidence {
  color: var(--op-muted-strong);
  font-size: 12px;
  line-height: 1.45;
  text-wrap: pretty;
}

.planActionEvidence {
  color: var(--op-muted);
}

.planActionCta {
  max-width: 124px;
  color: var(--op-primary-strong);
  font-size: 12px;
  font-weight: 800;
  text-align: right;
  overflow-wrap: anywhere;
}
```

- [ ] **Step 3: Run build**

Run:

```powershell
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 4: Commit action plan widget**

Run:

```powershell
git add web/src/features/dashboard/widgets/TodayActionPlan.tsx web/src/features/dashboard/dashboard.module.css
git commit -m "feat: AI add mission action plan"
```

Expected: commit succeeds.

---

### Task 4: Readiness Strip And Focus Workspace

**Files:**
- Create: `web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx`
- Create: `web/src/features/dashboard/widgets/FocusWorkspace.tsx`
- Modify: `web/src/features/dashboard/dashboard.module.css`

- [ ] **Step 1: Create `ApplicationReadinessStrip.tsx`**

Create `web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx`:

```tsx
import { Button, Tag } from 'antd';
import { CheckCircleOutlined, ExclamationCircleOutlined, WarningOutlined } from '@ant-design/icons';
import type { ReactNode } from 'react';
import type { ApplicationReadiness, ApplicationReadinessState } from '@/lib/missionControl';
import styles from '../dashboard.module.css';

interface Props {
  items: ApplicationReadiness[];
  focusApplicationId?: number;
  onFocus: (applicationId: number) => void;
}

const STATE_LABELS: Record<ApplicationReadinessState, string> = {
  ready: '就绪',
  watch: '关注',
  blocked: '阻塞',
};

const STATE_ICONS: Record<ApplicationReadinessState, ReactNode> = {
  ready: <CheckCircleOutlined />,
  watch: <WarningOutlined />,
  blocked: <ExclamationCircleOutlined />,
};

export default function ApplicationReadinessStrip({ items, focusApplicationId, onFocus }: Props) {
  if (items.length === 0) {
    return (
      <section className={styles.readinessStrip} aria-label="投递准备度">
        <div className={styles.readinessEmpty}>暂无活跃投递。添加投递后，这里会显示材料、日程和准备状态。</div>
      </section>
    );
  }

  return (
    <section className={styles.readinessStrip} aria-label="投递准备度">
      <div className={styles.sectionHeaderLine}>
        <div>
          <div className={styles.commandEyebrow}>Readiness</div>
          <h2 className={styles.sectionHeading}>重点投递准备度</h2>
        </div>
      </div>
      <div className={styles.readinessList}>
        {items.slice(0, 6).map((item) => (
          <button
            key={item.applicationId}
            type="button"
            className={`${styles.readinessCard} ${styles[`readiness-${item.readiness}`]} ${
              focusApplicationId === item.applicationId ? styles.readinessActive : ''
            }`}
            onClick={() => onFocus(item.applicationId)}
          >
            <span className={styles.readinessIcon} aria-hidden="true">
              {STATE_ICONS[item.readiness]}
            </span>
            <span className={styles.readinessBody}>
              <span className={styles.readinessTitle}>{item.companyName}</span>
              <span className={styles.readinessPosition}>{item.positionName}</span>
              <span className={styles.readinessEvidence}>{item.evidence[0] ?? '暂无准备风险'}</span>
            </span>
            <span className={styles.readinessTags}>
              <Tag>{STATE_LABELS[item.readiness]}</Tag>
              <Tag>{item.materialStatus}</Tag>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Create `FocusWorkspace.tsx`**

Create `web/src/features/dashboard/widgets/FocusWorkspace.tsx`:

```tsx
import { Button, Empty, Space, Tag } from 'antd';
import {
  CalendarOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  ReadOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import type { Application } from '@/types/application';
import type { ApplicationReadiness } from '@/lib/missionControl';
import type { ViewMode } from '@/layout/AppShell';
import styles from '../dashboard.module.css';

interface Props {
  application?: Application;
  readiness?: ApplicationReadiness;
  onOpenDetail: (applicationId: number) => void;
  onNavigate: (view: ViewMode) => void;
}

export default function FocusWorkspace({ application, readiness, onOpenDetail, onNavigate }: Props) {
  if (!application || !readiness) {
    return (
      <aside className={styles.focusWorkspace} aria-label="当前焦点">
        <Empty description="选择一个投递，查看关联材料、日程和准备入口。" />
      </aside>
    );
  }

  return (
    <aside className={styles.focusWorkspace} aria-labelledby="focus-workspace-title">
      <div className={styles.commandEyebrow}>Focus</div>
      <h2 id="focus-workspace-title" className={styles.sectionHeading}>
        {application.company_name}
      </h2>
      <p className={styles.focusPosition}>{application.position_name}</p>

      <div className={styles.focusTags}>
        <Tag>{application.status}</Tag>
        <Tag>{readiness.readiness}</Tag>
        <Tag>材料：{readiness.materialStatus}</Tag>
      </div>

      <div className={styles.focusEvidence}>
        {readiness.evidence.map((item) => (
          <div key={item} className={styles.focusEvidenceRow}>
            {item}
          </div>
        ))}
      </div>

      <Space direction="vertical" className={styles.focusActions}>
        <Button icon={<FolderOpenOutlined />} onClick={() => onOpenDetail(application.id)} block>
          打开投递详情
        </Button>
        <Button icon={<FileTextOutlined />} onClick={() => onOpenDetail(application.id)} block>
          查看材料包
        </Button>
        <Button icon={<CalendarOutlined />} onClick={() => onNavigate('calendar')} block>
          查看日程
        </Button>
        <Button icon={<ReadOutlined />} onClick={() => onNavigate('questions')} block>
          练习题目
        </Button>
        <Button type="primary" icon={<RocketOutlined />} onClick={() => onNavigate('mock')} block>
          进入模拟面试
        </Button>
      </Space>
    </aside>
  );
}
```

- [ ] **Step 3: Add readiness and focus CSS**

Append to `web/src/features/dashboard/dashboard.module.css`:

```css
.readinessStrip {
  padding: 18px;
  border-radius: 20px;
  background: var(--op-surface);
  box-shadow: var(--op-shadow-md);
}

.readinessList {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.readinessCard {
  min-height: 116px;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  border: none;
  border-radius: 16px;
  padding: 12px;
  background: var(--op-layout-bg);
  color: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 0 0 1px rgba(31, 29, 58, 0.05);
  transition-property: transform, box-shadow, background-color;
  transition-duration: 0.18s;
  transition-timing-function: var(--op-ease);
}

.readinessCard:hover,
.readinessCard:focus-visible,
.readinessActive {
  outline: none;
  transform: translateY(-1px);
  box-shadow: var(--op-shadow-lg);
}

.readinessCard:active {
  transform: scale(0.96);
}

.readinessIcon {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 13px;
  background: var(--op-info-soft);
  color: var(--op-info);
}

.readiness-blocked .readinessIcon {
  background: rgba(239, 68, 68, 0.14);
  color: var(--op-error);
}

.readiness-watch .readinessIcon {
  background: var(--op-action-soft);
  color: var(--op-action-strong);
}

.readinessBody {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.readinessTitle {
  color: var(--op-ink);
  font-size: 14px;
  font-weight: 800;
}

.readinessPosition,
.readinessEvidence {
  color: var(--op-muted-strong);
  font-size: 12px;
  line-height: 1.45;
  text-wrap: pretty;
}

.readinessTags {
  grid-column: 1 / -1;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.readinessEmpty {
  min-height: 92px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--op-muted-strong);
  text-align: center;
}

.focusWorkspace {
  min-width: 0;
  padding: 18px;
  border-radius: 20px;
  background: var(--op-surface);
  box-shadow: var(--op-shadow-md);
}

.focusPosition {
  margin: 6px 0 0;
  color: var(--op-muted-strong);
  font-size: 13px;
  line-height: 1.6;
}

.focusTags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 12px 0;
}

.focusEvidence {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 14px 0;
}

.focusEvidenceRow {
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--op-layout-bg);
  color: var(--op-muted-strong);
  font-size: 12px;
  line-height: 1.5;
}

.focusActions {
  width: 100%;
}
```

- [ ] **Step 4: Run build**

Run:

```powershell
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 5: Commit readiness and focus widgets**

Run:

```powershell
git add web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx web/src/features/dashboard/widgets/FocusWorkspace.tsx web/src/features/dashboard/dashboard.module.css
git commit -m "feat: AI add mission readiness focus"
```

Expected: commit succeeds.

---

### Task 5: Dashboard Integration

**Files:**
- Modify: `web/src/features/dashboard/DashboardView.tsx`
- Modify: `web/src/features/dashboard/dashboard.module.css`

- [ ] **Step 1: Update imports in `DashboardView.tsx`**

Add imports:

```tsx
import { getApplicationMaterialKit } from '@/services/materialKits';
import type { MaterialKitViewModel } from '@/types/materialKit';
import { deriveMissionControl } from '@/lib/missionControl';
import MissionHeader from './widgets/MissionHeader';
import WeeklyMissionPanel from './widgets/WeeklyMissionPanel';
import TodayActionPlan from './widgets/TodayActionPlan';
import ApplicationReadinessStrip from './widgets/ApplicationReadinessStrip';
import FocusWorkspace from './widgets/FocusWorkspace';
```

- [ ] **Step 2: Add focus state after selected insight state**

In `DashboardView`, after:

```tsx
const [selectedInsightId, setSelectedInsightId] = useState<string | null>(null);
```

Add:

```tsx
const [focusApplicationId, setFocusApplicationId] = useState<number | undefined>(undefined);
```

- [ ] **Step 3: Fetch material kits for active applications**

After the existing `const apps = appsQ.data ?? [];`, `const events = eventsQ.data ?? [];`, and `const offers = offersQ.data ?? [];` lines, add:

```tsx
const activeApplicationIds = useMemo(
  () =>
    apps
      .filter((app) => ['applied', 'assessment', 'written_test', 'interview', 'offer'].includes(app.status))
      .slice(0, 8)
      .map((app) => app.id),
  [apps],
);

const materialKitsQ = useQuery({
  queryKey: ['mission-control', 'material-kits', activeApplicationIds],
  queryFn: async () => {
    const kits = await Promise.all(activeApplicationIds.map((id) => getApplicationMaterialKit(id)));
    return kits.filter((kit): kit is MaterialKitViewModel => Boolean(kit));
  },
  enabled: activeApplicationIds.length > 0,
  retry: false,
});
```

This query is intentionally bounded to the first eight active applications so Mission Control does not fan out across a very large local database.

- [ ] **Step 4: Derive mission summary**

After `health`, add:

```tsx
const mission = useMemo(
  () =>
    deriveMissionControl({
      apps,
      events,
      offers,
      materialKits: materialKitsQ.data,
      practiceStats: practiceStatsQ.data,
      insights,
      healthLabel: health.label,
      weeklyTarget: 6,
      now,
    }),
  [apps, events, offers, materialKitsQ.data, practiceStatsQ.data, insights, health.label, now],
);

const effectiveFocusApplicationId = focusApplicationId ?? mission.focusApplicationId;
const focusApplication = effectiveFocusApplicationId
  ? apps.find((app) => app.id === effectiveFocusApplicationId)
  : undefined;
const focusReadiness = effectiveFocusApplicationId
  ? mission.readiness.find((item) => item.applicationId === effectiveFocusApplicationId)
  : undefined;
const nextMissionAction = mission.actions[0];
```

- [ ] **Step 5: Keep focus valid**

After the existing `useEffect` that clears stale selected insights, add:

```tsx
useEffect(() => {
  if (focusApplicationId && !apps.some((app) => app.id === focusApplicationId)) {
    setFocusApplicationId(undefined);
  }
}, [apps, focusApplicationId]);
```

- [ ] **Step 6: Replace dashboard content layout**

Replace the current non-empty dashboard JSX inside `<div className={styles.grid}>` with:

```tsx
<MissionHeader
  summary={mission}
  nextAction={nextMissionAction}
  onRunAction={handleAction}
  onAddApplication={onAddApplication}
/>
<WeeklyMissionPanel metrics={mission.metrics} onNavigate={onNavigate} />
<div className={styles.missionWorkspaceGrid}>
  <TodayActionPlan
    groups={mission.actionGroups}
    onAction={handleAction}
    onSeeAll={() => onNavigate('reminders')}
  />
  <FocusWorkspace
    application={focusApplication}
    readiness={focusReadiness}
    onOpenDetail={onOpenDetailById}
    onNavigate={onNavigate}
  />
</div>
<ApplicationReadinessStrip
  items={mission.readiness}
  focusApplicationId={effectiveFocusApplicationId}
  onFocus={setFocusApplicationId}
/>
<KpiCards kpis={kpis} />
<div className={styles.row2b}>
  <ConversionFunnel stages={funnel} />
  <MomentumChart buckets={momentum} />
</div>
<div className={styles.row2b}>
  <UpcomingSchedule events={events} />
  <div className={styles.card}>
    <div className={styles.cardTitle}>行动说明</div>
    <div className={styles.empty}>
      今日行动由投递停滞、即将到来的面试、Offer 截止期和到期题目自动推导。
    </div>
  </div>
</div>
```

- [ ] **Step 7: Add dashboard integration CSS**

Append to `web/src/features/dashboard/dashboard.module.css`:

```css
.missionWorkspaceGrid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
  gap: 14px;
  align-items: start;
}
```

Extend existing media queries:

```css
@media (max-width: 1100px) {
  .missionWorkspaceGrid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .weeklyMissionPanel,
  .readinessList {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .missionHeader {
    flex-direction: column;
    align-items: stretch;
  }

  .missionHeaderAction {
    width: 100%;
  }

  .missionHeaderAction :global(.ant-btn) {
    width: 100%;
  }

  .weeklyMissionPanel,
  .readinessList {
    grid-template-columns: 1fr;
  }

  .missionMetric,
  .planActionRow {
    grid-template-columns: 42px minmax(0, 1fr);
  }

  .metricState,
  .planActionCta {
    grid-column: 2;
    justify-self: start;
    text-align: left;
  }
}

@media (prefers-reduced-motion: reduce) {
  .missionMetric,
  .planActionRow,
  .readinessCard {
    animation: none;
    transition: none;
  }
}
```

If these selectors duplicate existing media blocks, merge them into the existing `@media` blocks instead of creating conflicting duplicates.

- [ ] **Step 8: Run frontend tests and build**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: PASS. Build may show existing chunk warnings.

- [ ] **Step 9: Commit dashboard integration**

Run:

```powershell
git add web/src/features/dashboard/DashboardView.tsx web/src/features/dashboard/dashboard.module.css
git commit -m "feat: AI integrate mission control dashboard"
```

Expected: commit succeeds.

---

### Task 6: Final Polish And Verification

**Files:**
- Modify only files from Tasks 1-5 if verification reveals defects.

- [ ] **Step 1: Scan for accidental transition-all and tiny hit areas**

Run:

```powershell
rg -n "transition:\\s*all|transition-property:\\s*all|min-height:\\s*(2[0-9]|3[0-9])px" web/src/features/dashboard web/src/theme/tokens.css
```

Expected: no `transition: all` or `transition-property: all` in touched files. If the min-height search finds a new interactive row below 40px, raise it to at least 44px.

- [ ] **Step 2: Run full frontend tests**

Run:

```powershell
npm.cmd test
```

Expected: PASS.

- [ ] **Step 3: Run frontend production build**

Run:

```powershell
npm.cmd run build
```

Expected: PASS. Record whether Vite still reports chunks larger than 500 kB.

- [ ] **Step 4: Run backend tests**

Run:

```powershell
go test ./...
```

Expected: PASS.

- [ ] **Step 5: Start local server for visual verification**

Run:

```powershell
go run ./cmd/oc start
```

Expected: server starts, usually on `http://localhost:8080`. Keep this terminal session running until browser checks are complete.

- [ ] **Step 6: Browser verification checklist**

Open `http://localhost:8080` and verify:

- Dashboard first screen starts with "本周求职作战台".
- Weekly Mission Panel shows six metric tiles.
- Today Action Plan opens `ActionDetailDrawer` when a row is clicked.
- Application Readiness Strip selects a focus application.
- Focus Workspace buttons navigate to existing board/calendar/questions/mock views.
- At mobile width around 375px, there is no horizontal scroll and no text overlap.
- Keyboard tab focus is visible on mission buttons, action rows, readiness cards, and drawer buttons.
- With reduced motion enabled in the browser or OS, layout remains usable and animations are removed.

- [ ] **Step 7: Stop local server**

Stop the `go run ./cmd/oc start` session with `Ctrl+C`.

Expected: terminal returns to prompt.

- [ ] **Step 8: Commit final polish if files changed**

If Step 1-6 required code or CSS fixes, run:

```powershell
git add web/src/lib/missionControl.ts web/src/lib/missionControl.test.ts web/src/features/dashboard/DashboardView.tsx web/src/features/dashboard/dashboard.module.css web/src/features/dashboard/widgets/MissionHeader.tsx web/src/features/dashboard/widgets/WeeklyMissionPanel.tsx web/src/features/dashboard/widgets/TodayActionPlan.tsx web/src/features/dashboard/widgets/ApplicationReadinessStrip.tsx web/src/features/dashboard/widgets/FocusWorkspace.tsx web/src/theme/tokens.css
git commit -m "fix: AI polish mission control verification"
```

Expected: commit succeeds if files changed. If no files changed, do not create an empty commit.

---

## Final Verification Before Completion

Run these commands fresh before reporting completion:

```powershell
npm.cmd test
npm.cmd run build
go test ./...
git status --short --branch
```

Completion criteria:

- All tests pass.
- Frontend build exits with code 0.
- Backend tests exit with code 0.
- Worktree is clean after commits.
- Any remaining warnings are explicitly reported.

## Spec Coverage Self-Review

- Weekly Mission Panel: Task 1 derives metrics; Task 2 renders metrics; Task 5 integrates it.
- Today Action Plan: Task 1 groups actions; Task 3 renders groups; Task 5 opens existing action drawer.
- Application Readiness Strip: Task 1 derives readiness; Task 4 renders cards; Task 5 wires focus selection.
- Focus Workspace: Task 4 creates linked workspace; Task 5 wires selected application.
- Design System Polish: Task 2 adds tokens; Tasks 2-5 add CSS; Task 6 verifies transitions, hit areas, responsiveness, focus, and reduced motion.
- Error handling and optional data degradation: Task 1 tests null optional arrays; Task 5 uses bounded material kit queries with `retry: false`; Task 6 browser verification checks empty and responsive states.
- Out-of-scope constraints: no backend tables, no automatic AI calls, no new dependencies, no form duplication.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-candidate-mission-control.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
