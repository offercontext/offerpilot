// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AppShell from './AppShell';

const app = {
  id: 7,
  company_name: 'ByteDance',
  position_name: 'Backend',
  applied_at: '2026-07-10T09:00:00Z',
};

const queryClientState = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
}));

vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: any) => {
    const key = options.queryKey?.[0];
    const dataByKey: Record<string, unknown> = {
      applications: [app],
      events: [],
      offers: [],
      questions: undefined,
    };
    return { data: dataByKey[key], isError: false, isLoading: false };
  },
  useQueryClient: () => queryClientState,
}));

vi.mock('@dnd-kit/core', () => ({
  DndContext: (props: any) => <div>{props.children}</div>,
  PointerSensor: class PointerSensor {},
  useSensor: () => ({}),
  useSensors: () => ({}),
}));

vi.mock('antd', () => {
  const Layout = Object.assign(
    (props: any) => <div>{props.children}</div>,
    { Content: (props: any) => <main>{props.children}</main> },
  );
  return {
    Button: (props: any) => <button type="button" onClick={props.onClick}>{props.children}</button>,
    Layout,
    Spin: () => <div>loading</div>,
    Tabs: () => <div />,
    message: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
  };
});

vi.mock('./Sidebar', () => ({
  default: (props: any) => (
    <nav>
      <button type="button" data-testid="nav-pilot" onClick={() => props.onChange('pilot')}>Pilot</button>
      <button type="button" data-testid="nav-board" onClick={() => props.onChange('board')}>Board</button>
      <button type="button" data-testid="nav-offers" onClick={() => props.onChange('offers')}>Offers</button>
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
    <section data-testid="application-detail">
      {props.application.id}
      <button type="button" data-testid="close-application" onClick={props.onClose}>Close</button>
      <button type="button" data-testid="open-pilot-opportunity-fit" onClick={() => props.onOpenPilotOpportunityFit?.(props.application)}>Evaluate</button>
    </section>
  ),
}));
vi.mock('@/features/pilot/PilotOpportunityFitCard', () => ({
  default: (props: any) => <section data-testid="pilot-opportunity-fit-card" data-draft-key={props.draft.pilotDraftKey} data-application-id={props.draft.applicationId} />,
}));
vi.mock('@/components/ChatPanel', () => ({
  default: (props: any) => (
    <section data-testid={`chat-${props.variant ?? 'drawer'}`}>
      <button
        type="button"
        data-testid={`open-offer-${props.variant ?? 'drawer'}`}
        onClick={() => props.onOpenEvidence?.({ kind: 'offer', id: 9 })}
      >
        Open offer
      </button>
      <button
        type="button"
        data-testid={`open-application-${props.variant ?? 'drawer'}`}
        onClick={() => props.onOpenEvidence?.({ kind: 'application', id: 7 })}
      >
        Open application
      </button>
      <button
        type="button"
        data-testid={`refresh-pilot-${props.variant ?? 'drawer'}`}
        onClick={() => props.onDataChanged?.()}
      >
        Refresh Pilot data
      </button>
    </section>
  ),
}));
vi.mock('@/components/KanbanBoard', () => ({ default: () => <div data-testid="board" /> }));
vi.mock('@/components/OfferCenterView', () => ({
  default: (props: any) => <output data-testid="offer-focus">{props.focusOfferId ?? 'none'}</output>,
}));
vi.mock('@/features/dashboard/DashboardView', () => ({ default: () => <div data-testid="dashboard" /> }));
vi.mock('@/features/pilot/PilotAttachmentContext', () => ({
  PilotAttachmentProvider: (props: any) => <>{props.children}</>,
  usePilotAttachmentStore: () => ({ addAttachment: vi.fn(), createNewDraftWithAttachment: vi.fn() }),
}));
vi.mock('@/features/pilot/attachmentHandoff', () => ({ retainPilotAttachmentKey: (_current: any, next: any) => next }));

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function render(ui: React.ReactNode) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(ui));
  return container;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  window.matchMedia = () => ({
    addEventListener: () => undefined,
    matches: false,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;
  window.scrollTo = vi.fn();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
  vi.clearAllMocks();
});

describe('AppShell evidence navigation', () => {
  it('opens one Application-scoped Pilot draft and keeps its key across view changes', async () => {
    const view = render(<AppShell />);
    await flush();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="open-application-page"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="open-pilot-opportunity-fit"]')?.click());
    await flush();

    const card = view.querySelector('[data-testid="pilot-opportunity-fit-card"]');
    expect(card?.getAttribute('data-application-id')).toBe('7');
    const draftKey = card?.getAttribute('data-draft-key');
    expect(draftKey).toBeTruthy();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-board"]')?.click());
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    expect(view.querySelector('[data-testid="pilot-opportunity-fit-card"]')?.getAttribute('data-draft-key')).toBe(draftKey);
  });

  it('invalidates the same-month calendar query after Pilot data changes', async () => {
    const view = render(<AppShell />);
    await flush();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="refresh-pilot-page"]')?.click());

    expect(queryClientState.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['calendar'] });
  });

  it('cancels unresolved non-application focus when a later application opens from narrow Pilot', async () => {
    const view = render(<AppShell />);
    await flush();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="open-offer-page"]')?.click());
    await flush();

    expect(view.querySelector('[data-testid="offer-focus"]')?.textContent).toBe('9');
    const applicationButton = view.querySelector<HTMLButtonElement>('[data-testid="open-application-drawer"]');
    expect(applicationButton).toBeInstanceOf(HTMLButtonElement);
    act(() => applicationButton?.click());
    await flush();

    expect(view.querySelector('[data-testid="application-detail"]')?.textContent).toContain('7');
    expect(view.querySelector('[data-testid="chat-drawer"]')).not.toBeNull();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="close-application"]')?.click());
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-offers"]')?.click());
    await flush();

    expect(view.querySelector('[data-testid="offer-focus"]')?.textContent).toBe('none');
  });

  it('clears an errored evidence target when the user leaves its destination', async () => {
    const view = render(<AppShell />);
    await flush();

    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="open-offer-page"]')?.click());
    await flush();

    expect(view.querySelector('[data-testid="offer-focus"]')?.textContent).toBe('9');
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-board"]')?.click());
    await flush();
    act(() => view.querySelector<HTMLButtonElement>('[data-testid="nav-offers"]')?.click());
    await flush();

    expect(view.querySelector('[data-testid="offer-focus"]')?.textContent).toBe('none');
  });
});
