// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AppShell from './AppShell';

const offer = {
  id: 42,
  application_id: 7,
  company_name: '星云数据',
  position_name: '后端工程师',
  status: 'pending',
  base_monthly: 28000,
  months_per_year: 12,
  signing_bonus: 0,
  equity: '',
  perks: '',
  deadline: '',
  notes: '',
  assessment: '',
  total_cash: 336000,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
} as const;

const opportunityFitState = vi.hoisted(() => ({
  createTriage: vi.fn(),
  confirmTriage: vi.fn(),
  createDeep: vi.fn(),
  getReview: vi.fn(),
  listReviews: vi.fn(),
  sourceConflict: vi.fn(),
}));

const baseDraft = (goal: string) => ({
  attemptKey: `${goal}-attempt`, confirmationKey: `${goal}-confirm`, goal,
  concerns: `${goal}-顾虑`, scenario: `${goal}-场景`, resultUnknown: false,
  pendingOperation: null, proposalId: null, selectedBlocks: [], edits: {},
  dimensionIds: [], sourceFingerprint: null, previewSnapshot: null, previewInputKey: null,
});

vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: { queryKey?: unknown[] }) => {
    const key = String(options.queryKey?.[0] ?? '');
    const data: Record<string, unknown> = {
      applications: [{ id: 7, company_name: '星云数据', position_name: '后端工程师', applied_at: '2026-08-01T00:00:00Z' }],
      events: [], offers: [offer], resumes: [{ id: 11, title: '简历' }], knowledge: [], questions: undefined,
      'application-jd-current': { current: { id: 1, application_id: 7, jd_text: 'JD text' } },
    };
    return { data: data[key], isError: false, isLoading: false, isFetching: false, error: null };
  },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock('@/services/opportunityFitReviews', () => ({
  createOpportunityFitV2Triage: opportunityFitState.createTriage,
  confirmOpportunityFitV2Triage: opportunityFitState.confirmTriage,
  createOpportunityFitV2DeepReview: opportunityFitState.createDeep,
  getOpportunityFitV2Review: opportunityFitState.getReview,
  findOpportunityFitV2SourceConflictStage: opportunityFitState.sourceConflict,
  listOpportunityFitV2Reviews: opportunityFitState.listReviews,
  listOpportunityFitReviews: vi.fn().mockResolvedValue([]),
  getOpportunityFitReview: vi.fn(),
  createOpportunityFitReview: vi.fn(),
  createOpportunityFitDeepReview: vi.fn(),
}));

vi.mock('@dnd-kit/core', () => ({
  DndContext: (props: any) => <div>{props.children}</div>,
  PointerSensor: class PointerSensor {},
  useSensor: () => ({}),
  useSensors: () => ({}),
}));

vi.mock('antd', () => {
  const Layout = Object.assign((props: any) => <div {...props}>{props.children}</div>, {
    Content: (props: any) => <main {...props}>{props.children}</main>,
  });
  return {
    Button: (props: any) => <button {...props} type="button" onClick={props.onClick}>{props.children}</button>,
    Layout,
    Spin: () => <div>loading</div>,
    Tabs: () => <div />,
    message: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
  };
});

vi.mock('./Sidebar', () => ({
  default: (props: any) => (
    <nav>
      <button type="button" data-testid="nav-offers" onClick={() => props.onChange('offers')}>Offers</button>
      <button type="button" data-testid="nav-pilot" onClick={() => props.onChange('pilot')}>Pilot</button>
    </nav>
  ),
}));
vi.mock('./TopBar', () => ({ default: () => <div /> }));
vi.mock('./CommandPalette', () => ({ default: () => <div /> }));
vi.mock('@/components/AddApplicationForm', () => ({ default: () => <div /> }));
vi.mock('@/components/ResumeUploadModal', () => ({ default: () => <div /> }));
vi.mock('@/components/AISettingsDrawer', () => ({ default: () => <div /> }));
vi.mock('@/components/ApplicationDetail', () => ({
  default: (props: any) => (
    <section data-testid="application-detail-harness">
      <button type="button" data-testid="open-opportunity-fit" onClick={() => props.onOpenPilotOpportunityFit?.({
        id: 7,
        company_name: '星云数据',
        position_name: '后端工程师',
      })}>
        打开岗位评估
      </button>
    </section>
  ),
}));
vi.mock('@/components/KanbanBoard', () => ({ default: () => <div /> }));
vi.mock('@/components/ApplicationListView', () => ({ default: () => <div /> }));
vi.mock('@/components/CalendarView', () => ({ default: () => <div /> }));
vi.mock('@/components/KnowledgeSourcesView', () => ({ default: () => <div /> }));
vi.mock('@/components/QuestionBankView', () => ({ default: () => <div /> }));
vi.mock('@/components/InterviewV01View', () => ({ default: () => <div /> }));
vi.mock('@/components/ResumeLibraryView', () => ({ default: () => <div /> }));
vi.mock('@/features/reminders/RemindersView', () => ({ default: () => <div /> }));
vi.mock('@/components/SettingsView', () => ({ default: () => <div /> }));
vi.mock('@/features/dashboard/DashboardView', () => ({
  default: (props: any) => (
    <section data-testid="dashboard-harness">
      <button type="button" data-testid="open-application-detail" onClick={() => props.onOpenDetailById?.(7)}>
        查看投递
      </button>
    </section>
  ),
}));
vi.mock('@/features/pilot/PilotAttachmentContext', () => ({
  PilotAttachmentProvider: (props: any) => <>{props.children}</>,
  usePilotAttachmentStore: () => ({ addAttachment: vi.fn(), createNewDraftWithAttachment: vi.fn() }),
}));
vi.mock('@/features/pilot/attachmentHandoff', () => ({ retainPilotAttachmentKey: (_current: unknown, next: unknown) => next }));
vi.mock('@/features/pilot/PilotOpportunityFitCard', () => ({ default: () => <div /> }));

vi.mock('@/components/OfferCenterView', () => ({
  default: (props: any) => (
    <section data-testid="offer-center-harness">
      <button type="button" data-testid="open-ui-offer" onClick={() => props.onNegotiationDraftChange?.(offer.id, baseDraft('UI 目标'))}>打开 UI 谈薪准备</button>
      <output data-testid="ui-draft-goal">{props.negotiationDrafts?.[offer.id]?.goal ?? ''}</output>
    </section>
  ),
}));

vi.mock('@/components/ChatPanel', () => ({
  default: (props: any) => (
    <section data-testid={`chat-${props.variant ?? 'drawer'}`}>
      <button type="button" data-testid="open-pilot-offer" onClick={() => props.onPrepareOfferNegotiation?.(offer)}>打开 Pilot 谈薪准备</button>
    </section>
  ),
}));

vi.mock('@/components/MockInterviewDrawer', () => ({ default: () => <div /> }));
vi.mock('@/components/OfferNegotiationDrawer', () => ({
  default: (props: any) => (
    <section data-testid="offer-negotiation-drawer-harness">
      <output data-testid="pilot-draft-goal">{props.draft?.goal ?? ''}</output>
      <button type="button" data-testid="save-pilot-draft" onClick={() => props.onDraftChange?.(baseDraft('Pilot 目标'))}>保存 Pilot 草稿</button>
      <button type="button" data-testid="close-pilot-drawer" onClick={props.onClose}>关闭</button>
    </section>
  ),
}));

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean | undefined; }
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLDivElement | null = null;

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('AppShell mounted Opportunity Fit confirmation recovery', () => {
  beforeEach(() => {
    opportunityFitState.createTriage.mockReset();
    opportunityFitState.confirmTriage.mockReset();
    opportunityFitState.createDeep.mockReset();
    opportunityFitState.getReview.mockReset();
    opportunityFitState.listReviews.mockReset();
    opportunityFitState.createTriage.mockResolvedValue({
      stage_id: 101,
      review_id: 201,
      resume_id: 11,
      jd_version_id: 1,
      stage: 'triage',
      schema_version: 2,
      stage_status: 'ready',
      parent_triage_stage_id: null,
      idempotency_key: 'pilot-triage-key',
      source_fingerprint_sha256: 'frozen-source',
      confirmation_token: 'triage-confirmation-token',
      proposal: {
        schema_version: 2,
        stage: 'triage',
        source: { kind: 'opportunity_fit', contract_version: 'opportunity_fit.v2', snapshot_version: '1' },
        summary: { text: 'Triage summary', rationale: 'evidence', evidence_refs: [] },
        conditions: [],
        risks: [],
        questions: [],
        next_steps: [],
      },
    });
    opportunityFitState.confirmTriage.mockRejectedValue({
      response: { data: { error_code: 'opportunity_fit_triage_confirmation_consumed' } },
    });
    opportunityFitState.getReview.mockResolvedValue({
      stages: [{
        stage_id: 101,
        review_id: 201,
        resume_id: 11,
        jd_version_id: 1,
        stage: 'triage',
        schema_version: 2,
        stage_status: 'confirmed',
        parent_triage_stage_id: null,
        idempotency_key: 'pilot-triage-key',
        source_fingerprint_sha256: 'frozen-source',
        confirmation_token: 'triage-confirmation-token',
        proposal: {
          schema_version: 2,
          stage: 'triage',
          source: { kind: 'opportunity_fit', contract_version: 'opportunity_fit.v2', snapshot_version: '1' },
          summary: { text: 'Confirmed summary', rationale: 'evidence', evidence_refs: [] },
          conditions: [],
          risks: [],
          questions: [],
          next_steps: [],
        },
      }],
    });
    opportunityFitState.listReviews.mockResolvedValue([]);
    window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
    window.scrollTo = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = null;
    host = null;
    vi.clearAllMocks();
  });

  it('recovers a consumed Pilot Triage confirmation from the mounted AppShell', async () => {
    await act(async () => root?.render(<AppShell />));
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="open-application-detail"]')?.click());
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="open-opportunity-fit"]')?.click());
    await flush();
    const resumeSelect = host?.querySelector<HTMLSelectElement>('select');
    if (!resumeSelect) throw new Error('Pilot resume selector was not mounted');
    resumeSelect.value = '11';
    act(() => resumeSelect.dispatchEvent(new Event('change', { bubbles: true })));
    await flush();
    const startButton = Array.from(host?.querySelectorAll<HTMLButtonElement>('button') ?? [])
      .find((button) => button.textContent?.includes('Triage'));
    if (!startButton) throw new Error('Pilot Triage start button was not mounted');
    act(() => startButton.click());
    await flush();
    const confirmation = host?.querySelector<HTMLElement>('[role="dialog"]');
    const confirmButton = confirmation?.querySelectorAll<HTMLButtonElement>('button')[1];
    if (!confirmButton) throw new Error('Pilot Triage confirmation button was not mounted');
    act(() => confirmButton.click());
    await flush();
    expect(opportunityFitState.createTriage).toHaveBeenCalledTimes(1);
    const triageButton = Array.from(host?.querySelectorAll<HTMLButtonElement>('button') ?? [])
      .find((button) => button.textContent?.includes('Triage'));
    if (!triageButton) throw new Error('Pilot Triage confirmation button was not mounted');
    act(() => triageButton.click());
    await flush();
    await flush();
    expect(opportunityFitState.confirmTriage).toHaveBeenCalledTimes(1);
    expect(opportunityFitState.getReview).toHaveBeenCalledWith(7, 201);
    const restartButton = host?.querySelector<HTMLButtonElement>('[aria-label="重新开始岗位评估"]');
    if (!restartButton) throw new Error('Pilot restart button was not mounted');
    act(() => restartButton.click());
    await flush();
    expect(host?.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('JD text');
    expect(host?.querySelector<HTMLSelectElement>('select')?.value).toBe('');
  });

  it('restores a persisted Pilot Triage source conflict after a JD race', async () => {
    opportunityFitState.createTriage.mockRejectedValue({
      response: { status: 409, data: { error_code: 'application_jd_source_conflict' } },
    });
    opportunityFitState.sourceConflict.mockResolvedValue({
      stage_id: 101,
      review_id: 201,
      resume_id: 11,
      jd_version_id: 1,
      stage: 'triage',
      schema_version: 2,
      stage_status: 'source_conflict',
      parent_triage_stage_id: null,
      idempotency_key: 'pilot-triage-key',
      source_fingerprint_sha256: 'frozen-source',
      confirmation_token: null,
      proposal: null,
    });

    await act(async () => root?.render(<AppShell />));
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="open-application-detail"]')?.click());
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="open-opportunity-fit"]')?.click());
    await flush();
    const resumeSelect = host?.querySelector<HTMLSelectElement>('select');
    if (!resumeSelect) throw new Error('Pilot resume selector was not mounted');
    resumeSelect.value = '11';
    act(() => resumeSelect.dispatchEvent(new Event('change', { bubbles: true })));
    await flush();
    const startButton = Array.from(host?.querySelectorAll<HTMLButtonElement>('button') ?? [])
      .find((button) => button.textContent?.includes('Triage'));
    if (!startButton) throw new Error('Pilot Triage start button was not mounted');
    act(() => startButton.click());
    await flush();
    const confirmation = host?.querySelector<HTMLElement>('[role="dialog"]');
    const confirmButton = confirmation?.querySelectorAll<HTMLButtonElement>('button')[1];
    if (!confirmButton) throw new Error('Pilot Triage confirmation button was not mounted');
    act(() => confirmButton.click());
    await flush();
    await flush();

    expect(opportunityFitState.sourceConflict).toHaveBeenCalledWith(7, 'triage', expect.any(String), undefined);
    expect(opportunityFitState.sourceConflict.mock.calls[0][2]).toBe(
      opportunityFitState.createTriage.mock.calls[0][1].idempotency_key,
    );
    expect(host?.textContent).toContain('岗位资料版本已变化');
    expect(host?.querySelector('[aria-label="重新开始岗位评估"]')).not.toBeNull();
  });
});

describe('AppShell Offer negotiation draft isolation', () => {
  beforeEach(() => {
    window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
    window.scrollTo = vi.fn();
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = null;
    host = null;
    vi.clearAllMocks();
  });

  it('keeps UI and Pilot drafts isolated for the same Offer', async () => {
    await act(async () => root?.render(<AppShell />));
    await flush();

    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="nav-offers"]')?.click());
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="open-ui-offer"]')?.click());
    await flush();
    expect(host?.querySelector('[data-testid="ui-draft-goal"]')?.textContent).toBe('UI 目标');

    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    const pilotOpenButton = host?.querySelector<HTMLButtonElement>('[data-testid="open-pilot-offer"]');
    pilotOpenButton?.focus();
    act(() => pilotOpenButton?.click());
    await flush();
    expect(host?.querySelector('[data-testid="pilot-draft-goal"]')?.textContent).toBe('');
    const overlay = host?.querySelector<HTMLElement>('[data-testid="offer-negotiation-overlay"]');
    expect(overlay).not.toBeNull();
    expect(overlay?.style.position).toBe('fixed');
    expect(overlay?.getAttribute('aria-label')).toBe(`为 ${offer.company_name} 准备谈薪`);
    expect(overlay?.querySelector('[data-testid="offer-negotiation-drawer-harness"]')).not.toBeNull();
    expect(overlay?.contains(document.activeElement)).toBe(true);
    const focusable = Array.from(overlay?.querySelectorAll<HTMLElement>('button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])') ?? [])
      .filter((element) => !element.hasAttribute('disabled'));
    expect(focusable.length).toBeGreaterThan(1);
    focusable[focusable.length - 1]?.focus();
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })));
    expect(document.activeElement).toBe(focusable[0]);
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    await flush();
    expect(host?.querySelector('[data-testid="offer-negotiation-overlay"]')).toBeNull();
    expect(document.activeElement).toBe(pilotOpenButton);

    act(() => pilotOpenButton?.click());
    await flush();
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="save-pilot-draft"]')?.click());
    await flush();
    expect(host?.querySelector('[data-testid="pilot-draft-goal"]')?.textContent).toBe('Pilot 目标');

    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="close-pilot-drawer"]')?.click());
    act(() => host?.querySelector<HTMLButtonElement>('[data-testid="nav-offers"]')?.click());
    await flush();
    expect(host?.querySelector('[data-testid="ui-draft-goal"]')?.textContent).toBe('UI 目标');
  });
});
