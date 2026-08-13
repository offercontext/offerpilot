// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardView from './DashboardView';
import type { NextStepFacts } from '@/lib/nextStepSuggestions';
import type { Application } from '@/types/application';

const state = vi.hoisted(() => ({
  material: { status: 'success' as 'loading' | 'error' | 'success', kits: [] as unknown[] },
  queryStatus: {
    events: 'success' as 'loading' | 'error' | 'success',
    offers: 'success' as 'loading' | 'error' | 'success',
    practice: 'success' as 'loading' | 'error' | 'success',
  },
  applications: [] as unknown[],
  setOnboardingForceOpen: vi.fn(),
  writes: {
    createApplication: vi.fn(),
    updateApplication: vi.fn(),
    generateApplicationMaterialKit: vi.fn(),
    updateMaterialKit: vi.fn(),
    createMaterialRevisionProposal: vi.fn(),
    acceptMaterialRevisionProposal: vi.fn(),
    rejectMaterialRevisionProposal: vi.fn(),
    createInterviewPreparationProposal: vi.fn(),
    createInterviewReviewProposal: vi.fn(),
    createInterviewKnowledgePreview: vi.fn(),
    confirmInterviewKnowledgeCapture: vi.fn(),
    createMockInterviewAttempt: vi.fn(),
    submitMockInterviewTurn: vi.fn(),
    createMockInterviewFeedback: vi.fn(),
    confirmMockInterviewReviewDraft: vi.fn(),
    createEvent: vi.fn(),
    updateEvent: vi.fn(),
  },
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
    if (key === 'events') return { data: [], isLoading: state.queryStatus.events === 'loading', isError: state.queryStatus.events === 'error', isSuccess: state.queryStatus.events === 'success' };
    if (key === 'offers') return { data: [], isLoading: state.queryStatus.offers === 'loading', isError: state.queryStatus.offers === 'error', isSuccess: state.queryStatus.offers === 'success' };
    if (key === 'questions') return { data: { total: 0, new: 0, practicing: 0, mastered: 0, due: 0, today_reviews: 0, streak_days: 0 }, isLoading: state.queryStatus.practice === 'loading', isError: state.queryStatus.practice === 'error', isSuccess: state.queryStatus.practice === 'success' };
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

vi.mock('@/services/applications', () => ({
  listApplications: vi.fn(),
  createApplication: state.writes.createApplication,
  updateApplication: state.writes.updateApplication,
}));
vi.mock('@/services/events', () => ({
  listEvents: vi.fn(),
  createEvent: state.writes.createEvent,
  updateEvent: state.writes.updateEvent,
}));
vi.mock('@/services/offers', () => ({ listOffers: vi.fn() }));
vi.mock('@/services/materialKits', () => ({
  getApplicationMaterialKit: vi.fn(),
  generateApplicationMaterialKit: state.writes.generateApplicationMaterialKit,
  updateMaterialKit: state.writes.updateMaterialKit,
}));
vi.mock('@/services/materialRevisionProposals', () => ({
  createMaterialRevisionProposal: state.writes.createMaterialRevisionProposal,
  acceptMaterialRevisionProposal: state.writes.acceptMaterialRevisionProposal,
  rejectMaterialRevisionProposal: state.writes.rejectMaterialRevisionProposal,
}));
vi.mock('@/services/interviewPreparationProposals', () => ({
  createInterviewPreparationProposal: state.writes.createInterviewPreparationProposal,
}));
vi.mock('@/services/interviewReviewProposals', () => ({
  createInterviewReviewProposal: state.writes.createInterviewReviewProposal,
}));
vi.mock('@/services/interviewKnowledgeCapture', () => ({
  createInterviewKnowledgePreview: state.writes.createInterviewKnowledgePreview,
  confirmInterviewKnowledgeCapture: state.writes.confirmInterviewKnowledgeCapture,
}));
vi.mock('@/services/mockInterviews', () => ({
  createMockInterviewAttempt: state.writes.createMockInterviewAttempt,
  submitMockInterviewTurn: state.writes.submitMockInterviewTurn,
  createMockInterviewFeedback: state.writes.createMockInterviewFeedback,
  confirmMockInterviewReviewDraft: state.writes.confirmMockInterviewReviewDraft,
}));
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
      <output data-testid="candidate-state-key">{props.suggestions.candidates[0]?.stateKey ?? 'none'}</output>
      <output data-testid="session-disposition">{props.sessionState?.disposition ?? 'none'}</output>
      <button type="button" data-testid="run-suggestion" onClick={() => props.onNavigate(props.suggestions.candidates[0].destination)} />
      <button
        type="button"
        data-testid="snooze-suggestion"
        onClick={() => {
          const candidate = props.suggestions.candidates[0];
          props.onSetDisposition(props.applicationId, candidate.id, {
            stateKey: candidate.stateKey,
            disposition: 'snoozed',
          });
        }}
      />
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
vi.mock('./widgets/WeeklyMissionPanel', () => ({
  default: (props: { unavailableKinds?: string[] }) => (
    <output data-testid="weekly-unavailable-kinds">{props.unavailableKinds?.join(',') ?? ''}</output>
  ),
}));
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

let resumeVersion = 'v1';

let root: Root | undefined;
let container: HTMLDivElement | undefined;

function renderDashboard(
  sessionStates: Record<string, { stateKey: string; disposition: 'snoozed' | 'ignored' }> = {},
  getFacts: () => NextStepFacts = () => facts,
) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const onSetDisposition = vi.fn((applicationId: number, suggestionId: string, nextState: { stateKey: string; disposition: 'snoozed' | 'ignored' } | null) => {
    const key = `${applicationId}:${suggestionId}`;
    if (nextState) sessionStates[key] = nextState;
    else delete sessionStates[key];
  });
  const onNextStepNavigate = vi.fn();
  const onPruneDisposition = vi.fn((applicationId: number, suggestionId: string, stateKey: string) => {
    const key = `${applicationId}:${suggestionId}`;
    if (sessionStates[key] && sessionStates[key].stateKey !== stateKey) delete sessionStates[key];
  });
  const render = (factsProvider = getFacts) => act(() => root?.render(
    <DashboardView
      onNavigate={vi.fn()}
      onOpenDetailById={vi.fn()}
      onAddApplication={vi.fn()}
      onOnboardingAction={vi.fn()}
      nextStepFactsForApplication={factsProvider}
      suggestionSessionStates={sessionStates}
      onSetDisposition={onSetDisposition}
      onNextStepNavigate={onNextStepNavigate}
      isNextStepNavigationAvailable={() => true}
      onNextStepReadonlyNavigate={vi.fn()}
      isNextStepReadonlyNavigationAvailable={() => false}
      onPruneDisposition={onPruneDisposition}
    />,
  ));
  render();
  return { view: container, onSetDisposition, onNextStepNavigate, onPruneDisposition, rerender: render };
}

beforeEach(() => {
  state.material = { status: 'success', kits: [] };
  state.queryStatus = { events: 'success', offers: 'success', practice: 'success' };
  state.applications = [app];
  resumeVersion = 'v1';
  Object.values(state.writes).forEach((write) => write.mockClear());
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

  it('passes loading and failed query domains to the weekly summary as unavailable', () => {
    state.queryStatus = { events: 'loading', offers: 'error', practice: 'success' };
    state.material = { status: 'error', kits: [] };
    const { view } = renderDashboard();

    expect(view?.querySelector('[data-testid="weekly-unavailable-kinds"]')?.textContent).toBe(
      'interviews,offers,materials',
    );
  });

  it('lets the real Dashboard effect report a stale candidate state key', () => {
    state.material = { status: 'loading', kits: [] };
    const { onPruneDisposition } = renderDashboard({
      '1:application_detail': { stateKey: 'stale', disposition: 'ignored' },
    });
    expect(onPruneDisposition).toHaveBeenCalledWith(1, 'application_detail', expect.any(String));
  });

  it('clears a snoozed state after a real rerender changes the Resume version', () => {
    const sessionStates: Record<string, { stateKey: string; disposition: 'snoozed' | 'ignored' }> = {};
    const getFacts = () => ({
      ...facts,
      availableResumes: { status: 'known' as const, value: [{ id: 3, version: resumeVersion } as never] },
    });
    state.material = { status: 'loading', kits: [] };
    const { view, rerender, onSetDisposition } = renderDashboard(sessionStates, getFacts);

    const snoozeButton = view?.querySelector<HTMLButtonElement>('[data-testid="snooze-suggestion"]');
    expect(snoozeButton).not.toBeNull();
    act(() => snoozeButton?.click());
    expect(onSetDisposition).toHaveBeenCalledTimes(1);
    expect(onSetDisposition.mock.calls[0]).toEqual([
      1,
      'application_detail',
      { stateKey: expect.any(String), disposition: 'snoozed' },
    ]);
    expect(sessionStates['1:application_detail']?.disposition).toBe('snoozed');
    rerender();
    expect(view?.querySelector('[data-testid="session-disposition"]')?.textContent).toBe('snoozed');

    resumeVersion = 'v2';
    rerender(() => getFacts());
    expect(sessionStates['1:application_detail']).toBeUndefined();
    rerender(() => getFacts());
    expect(view?.querySelector('[data-testid="session-disposition"]')?.textContent).toBe('none');
  });

  it('navigates the mounted suggestion without invoking write callbacks', () => {
    const { view, onNextStepNavigate, onSetDisposition } = renderDashboard();
    act(() => view?.querySelector<HTMLButtonElement>('[data-testid="run-suggestion"]')?.click());
    expect(onNextStepNavigate).toHaveBeenCalled();
    expect(onSetDisposition).not.toHaveBeenCalled();
    expect(state.setOnboardingForceOpen).not.toHaveBeenCalled();
    Object.values(state.writes).forEach((write) => expect(write).not.toHaveBeenCalled());
  });
});
