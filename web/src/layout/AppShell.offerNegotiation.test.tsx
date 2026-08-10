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
      events: [], offers: [offer], resumes: [], knowledge: [], questions: undefined,
    };
    return { data: data[key], isError: false, isLoading: false, isFetching: false, error: null };
  },
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
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
  const Typography = {
    Paragraph: (props: any) => <p>{props.children}</p>,
    Text: (props: any) => <span>{props.children}</span>,
    Title: (props: any) => <h2>{props.children}</h2>,
  };
  return {
    Button: (props: any) => <button {...props} type="button" onClick={props.onClick}>{props.children}</button>,
    Layout,
    Spin: () => <div>loading</div>,
    Tabs: () => <div />,
    Typography,
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
vi.mock('@/components/ApplicationDetail', () => ({ default: () => <div /> }));
vi.mock('@/components/KanbanBoard', () => ({ default: () => <div /> }));
vi.mock('@/components/ApplicationListView', () => ({ default: () => <div /> }));
vi.mock('@/components/CalendarView', () => ({ default: () => <div /> }));
vi.mock('@/components/KnowledgeSourcesView', () => ({ default: () => <div /> }));
vi.mock('@/components/QuestionBankView', () => ({ default: () => <div /> }));
vi.mock('@/components/InterviewV01View', () => ({ default: () => <div /> }));
vi.mock('@/components/ResumeLibraryView', () => ({ default: () => <div /> }));
vi.mock('@/features/reminders/RemindersView', () => ({ default: () => <div /> }));
vi.mock('@/components/SettingsView', () => ({ default: () => <div /> }));
vi.mock('@/features/dashboard/DashboardView', () => ({ default: () => <div /> }));
vi.mock('@/features/pilot/PilotAttachmentContext', () => ({
  PilotAttachmentProvider: (props: any) => <>{props.children}</>,
  usePilotAttachmentStore: () => ({ addAttachment: vi.fn(), createNewDraftWithAttachment: vi.fn() }),
}));
vi.mock('@/features/pilot/attachmentHandoff', () => ({ retainPilotAttachmentKey: (_current: unknown, next: unknown) => next }));
vi.mock('@/features/pilot/PilotOpportunityFitCard', () => ({ default: () => <div /> }));
vi.mock('@/features/pilot/PilotOpportunityFitV2Card', () => ({ default: () => <div /> }));

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
