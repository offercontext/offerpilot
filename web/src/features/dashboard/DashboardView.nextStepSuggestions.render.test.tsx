// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardView from './DashboardView';
import type { NextStepFacts } from '@/lib/nextStepSuggestions';
import type { Application } from '@/types/application';

const state = vi.hoisted(() => ({
  material: { status: 'success' as 'loading' | 'error' | 'success', kits: [] as unknown[] },
  applications: [] as unknown[],
  setOnboardingForceOpen: vi.fn(),
}));

const app = {
  id: 1,
  company_name: 'Example Co.',
  position_name: 'Engineer',
  job_url: '',
  status: 'interview' as const,
  source: 'manual',
  notes: '',
  applied_at: '2026-07-01T00:00:00Z',
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
} as Application;

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useQuery: (options: { queryKey?: unknown[] }) => {
    const key = options.queryKey?.[0];
    if (key === 'applications') return { data: state.applications, isLoading: false, isError: false, isSuccess: true };
    if (key === 'events') return { data: [], isLoading: false, isError: false, isSuccess: true };
    if (key === 'offers') return { data: [], isLoading: false, isError: false, isSuccess: true };
    if (key === 'questions') return { data: { total: 0, new: 0, practicing: 0, mastered: 0, due: 0, today_reviews: 0, streak_days: 0 }, isLoading: false, isError: false, isSuccess: true };
    if (key === 'onboarding') return { data: null, isLoading: false, isError: false, isSuccess: true };
    if (key === 'mission-control') {
      return {
        data: state.material.kits,
        isLoading: state.material.status === 'loading',
        isError: state.material.status === 'error',
        isSuccess: state.material.status === 'success',
      };
    }
    return { data: [], isLoading: false, isError: false, isSuccess: true };
  },
}));

vi.mock('@/services/applications', () => ({ listApplications: vi.fn() }));
vi.mock('@/services/events', () => ({ listEvents: vi.fn() }));
vi.mock('@/services/offers', () => ({ listOffers: vi.fn() }));
vi.mock('@/services/materialKits', () => ({ getApplicationMaterialKit: vi.fn() }));
vi.mock('@/services/questions', () => ({ getPracticeStats: vi.fn() }));
vi.mock('@/services/onboarding', () => ({
  getOnboarding: vi.fn(),
  ONBOARDING_QUERY_KEY: ['onboarding'],
  setOnboardingForceOpen: state.setOnboardingForceOpen,
}));

vi.mock('@/lib/actionHints', () => ({ deriveActionHints: () => [] }));
vi.mock('@/lib/missionControl', () => ({
  deriveMissionControl: () => ({
    focusApplicationId: 1,
    readiness: [{ applicationId: 1 }],
    actions: [],
    metrics: {},
    actionGroups: [],
  }),
}));
vi.mock('@/lib/pipelineInsights', () => ({
  summarizePipelineHealth: () => ({ label: 'ok' }),
}));
vi.mock('@/lib/insights', () => ({
  computeKpis: () => ({}),
  computeFunnel: () => ({}),
  computeMomentum: () => ({}),
}));

vi.mock('@/components/NextStepSuggestions', () => ({
  default: (props: any) => (
    <section data-testid="next-step-suggestions">
      <output data-testid="candidate-id">{props.suggestions.candidates[0]?.id ?? 'none'}</output>
      <button type="button" data-testid="run-suggestion" onClick={() => props.onNavigate(props.suggestions.candidates[0].destination)} />
    </section>
  ),
}));

vi.mock('antd', () => ({
  Alert: (props: { children?: ReactNode }) => <div>{props.children}</div>,
  Skeleton: () => <div>loading</div>,
  Button: (props: { children?: ReactNode; onClick?: () => void }) => <button type="button" onClick={props.onClick}>{props.children}</button>,
}));

vi.mock('./widgets/KpiCards', () => ({ default: () => null }));
vi.mock('./widgets/ConversionFunnel', () => ({ default: () => null }));
vi.mock('./widgets/MomentumChart', () => ({ default: () => null }));
vi.mock('./widgets/UpcomingSchedule', () => ({ default: () => null }));
vi.mock('./widgets/MissionHeader', () => ({ default: () => null }));
vi.mock('./widgets/WeeklyMissionPanel', () => ({ default: () => null }));
vi.mock('./widgets/TodayActionPlan', () => ({ default: () => null }));
vi.mock('./widgets/ApplicationReadinessStrip', () => ({ default: () => null }));
vi.mock('./widgets/FocusWorkspace', () => ({ default: () => null }));
vi.mock('@/features/onboarding/OnboardingChecklist', () => ({ default: () => null }));
vi.mock('@/features/pipeline/ActionDetailDrawer', () => ({ default: () => null }));
vi.mock('./dashboard.module.css', () => ({ default: {} }));

const facts: NextStepFacts = {
  application: { status: 'known' as const, value: app },
  availableResumes: { status: 'known' as const, value: [{ id: 3, version: 'v1' } as never] },
  events: { status: 'known' as const, value: [] },
  offers: { status: 'known' as const, value: [] },
  confirmedKnowledge: { status: 'known' as const, value: [] },
  practiceStats: { status: 'known' as const, value: { total: 0, new: 0, practicing: 0, mastered: 0, due: 0, today_reviews: 0, streak_days: 0 } },
  jd: { status: 'known' as const, value: 'JD' },
  fitReview: { status: 'known' as const, value: {} },
  materialKit: { status: 'unknown' as const, reason: 'not_loaded' as const },
  interviewPreparationHistory: { status: 'known' as const, value: [] },
  mockInterviewHistory: { status: 'known' as const, value: [] },
};

let root: Root | undefined;
let container: HTMLDivElement | undefined;

function renderDashboard(sessionStates: Record<string, { stateKey: string; disposition: 'snoozed' | 'ignored' }> = {}) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const onSetDisposition = vi.fn();
  const onNextStepNavigate = vi.fn();
  const onPruneDisposition = vi.fn();
  act(() => root?.render(
    <DashboardView
      onNavigate={vi.fn()}
      onOpenDetailById={vi.fn()}
      onAddApplication={vi.fn()}
      onOnboardingAction={vi.fn()}
      nextStepFactsForApplication={() => facts}
      suggestionSessionStates={sessionStates}
      onSetDisposition={onSetDisposition}
      onNextStepNavigate={onNextStepNavigate}
      isNextStepNavigationAvailable={() => true}
      onNextStepReadonlyNavigate={vi.fn()}
      isNextStepReadonlyNavigationAvailable={() => false}
      onPruneDisposition={onPruneDisposition}
    />,
  ));
  return { view: container, onSetDisposition, onNextStepNavigate, onPruneDisposition };
}

beforeEach(() => {
  state.material = { status: 'success', kits: [] };
  state.applications = [app];
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('DashboardView next-step facts', () => {
  it.each([
    ['loading', 'application_detail'],
    ['error', 'application_detail'],
  ] as const)('maps Material Kit %s to unknown facts', (status, expectedCandidate) => {
    state.material = { status, kits: [] };
    const { view } = renderDashboard();
    expect(view?.querySelector('[data-testid="candidate-id"]')?.textContent).toBe(expectedCandidate);
  });

  it('maps partial Material Kit coverage to unknown facts', () => {
    state.applications = [app, ...Array.from({ length: 8 }, (_, index) => ({ ...app, id: index + 2 }))];
    state.material = { status: 'success', kits: [] };
    const { view } = renderDashboard();
    expect(view?.querySelector('[data-testid="candidate-id"]')?.textContent).toBe('application_detail');
  });

  it('lets the real Dashboard effect report a stale candidate state key', () => {
    state.material = { status: 'loading', kits: [] };
    const { onPruneDisposition } = renderDashboard({
      '1:application_detail': { stateKey: 'stale', disposition: 'ignored' },
    });
    expect(onPruneDisposition).toHaveBeenCalledWith(1, 'application_detail', expect.any(String));
  });

  it('navigates the mounted suggestion without invoking write callbacks', () => {
    const { view, onNextStepNavigate, onSetDisposition } = renderDashboard();
    act(() => view?.querySelector<HTMLButtonElement>('[data-testid="run-suggestion"]')?.click());
    expect(onNextStepNavigate).toHaveBeenCalled();
    expect(onSetDisposition).not.toHaveBeenCalled();
    expect(state.setOnboardingForceOpen).not.toHaveBeenCalled();
  });
});
