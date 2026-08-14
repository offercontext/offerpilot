// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AppShell from './AppShell';

const mockServices = vi.hoisted(() => ({ discard: vi.fn() }));

vi.mock('@tanstack/react-query', () => ({
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: () => ({ data: [], isError: false, isLoading: false, isFetching: false, error: null }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock('@dnd-kit/core', () => ({
  DndContext: (props: { children: ReactNode }) => <div>{props.children}</div>,
  PointerSensor: class PointerSensor {}, useSensor: () => ({}), useSensors: () => ({}),
}));
vi.mock('antd', () => {
  const Layout = Object.assign((props: Record<string, unknown> & { children?: ReactNode }) => <div>{props.children}</div>, {
    Content: (props: { children?: ReactNode }) => <main>{props.children}</main>,
  });
  return {
    Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props} />,
    Layout,
    Spin: () => <div>loading</div>,
    Tabs: () => <div />,
    message: { warning: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() },
  };
});
vi.mock('@/services/applicationJdVersions', () => ({
  getCurrentApplicationJd: vi.fn().mockResolvedValue({ current: { id: 4, jd_text: '后端工程师 JD' } }),
}));
vi.mock('@/services/mockInterviews', () => ({ discardMockInterviewAttempt: mockServices.discard }));
vi.mock('./Sidebar', () => ({
  default: (props: { onChange: (view: string) => void }) => <nav>
    <button type="button" data-testid="nav-interview" onClick={() => props.onChange('interview')}>面试</button>
    <button type="button" data-testid="nav-pilot" onClick={() => props.onChange('pilot')}>Pilot</button>
  </nav>,
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
vi.mock('@/components/OfferCenterView', () => ({ default: () => <div /> }));
vi.mock('@/components/ResumeLibraryView', () => ({ default: () => <div /> }));
vi.mock('@/components/SettingsView', () => ({ default: () => <div /> }));
vi.mock('@/features/dashboard/DashboardView', () => ({ default: () => <div /> }));
vi.mock('@/features/reminders/RemindersView', () => ({ default: () => <div /> }));
vi.mock('@/components/OfferNegotiationDrawer', () => ({ default: () => <div /> }));
vi.mock('@/components/InterviewStoryLibraryView', () => ({ default: () => <div /> }));
vi.mock('@/components/InterviewStoryDrawer', () => ({
  createInterviewStoryDraft: () => ({}), default: () => <div />,
}));
vi.mock('@/features/pilot/PilotAttachmentContext', () => ({
  PilotAttachmentProvider: (props: { children: ReactNode }) => <>{props.children}</>,
  usePilotAttachmentStore: () => ({ addAttachment: vi.fn(), createNewDraftWithAttachment: vi.fn() }),
}));
vi.mock('@/features/pilot/attachmentHandoff', () => ({ retainPilotAttachmentKey: (_current: unknown, next: unknown) => next }));
vi.mock('@/features/pilot/PilotOpportunityFitCard', () => ({ default: () => <div /> }));
vi.mock('@/features/pilot/PilotOpportunityFitV2Card', () => ({ default: () => <div /> }));
vi.mock('@/features/pilotMascot/PilotMascot', () => ({ default: () => <div /> }));
vi.mock('@/components/InterviewV01View', () => ({
  default: (props: { onOpenVoiceCoachingGrowth?: () => void }) => (
    <button type="button" data-testid="open-ui-growth" onClick={props.onOpenVoiceCoachingGrowth}>表达成长</button>
  ),
}));

const recommendation = {
  focus_kind: 'long_pause_control',
  title: '减少长停顿',
  reason: '连续长停顿仍较明显',
  source_snapshot_ids: [17, 16],
  source_snapshot_id: 17,
  application_id: 5,
  event_id: 9,
  question_text: '请介绍一次线上故障处理经历。',
  source_available: true,
};

vi.mock('@/components/VoiceCoachingGrowthView', () => ({
  default: (props: { onBack: () => void; onPractice: (input: typeof recommendation) => void }) => (
    <section data-testid="voice-growth-view">
      <button type="button" data-testid="back-growth" onClick={props.onBack}>返回</button>
      <button type="button" data-testid="practice-growth" onClick={() => props.onPractice(recommendation)}>再练一次</button>
    </section>
  ),
}));
vi.mock('@/components/MockInterviewDrawer', () => ({
  default: (props: {
    draft: { attemptId?: number | null; voicePracticeFocus?: { title?: string } | null };
    onDraftChange: (patch: Record<string, unknown>) => void;
    onClose: () => void;
  }) => (
    <section>
      <output data-testid="mock-focus" data-attempt-id={props.draft.attemptId ?? 'none'}>{props.draft.voicePracticeFocus?.title ?? 'none'}</output>
      <button type="button" data-testid="mark-voice-saved" onClick={() => props.onDraftChange({ attemptId: 41, hasSavedVoiceCoachingSnapshot: true })}>saved</button>
      <button type="button" data-testid="mark-voice-confirmed-only" onClick={() => props.onDraftChange({ attemptId: 40, answerSubmitted: false, hasSubmittedVoiceAnswer: false, voiceCoachingReview: { turnNo: 1, saveState: 'idle' } })}>confirmed only</button>
      <button type="button" data-testid="mark-voice-skipped" onClick={() => props.onDraftChange({ attemptId: 42, answerSubmitted: true, hasSubmittedVoiceAnswer: true, voiceCoachingReview: null })}>skipped</button>
      <button type="button" data-testid="mark-voice-unknown" onClick={() => props.onDraftChange({ attemptId: 43, answerSubmitted: true, hasSubmittedVoiceAnswer: true, voiceCoachingReview: { turnNo: 1, saveState: 'unknown' } })}>unknown</button>
      <button type="button" data-testid="close-mock" onClick={props.onClose}>close</button>
    </section>
  ),
}));
vi.mock('@/components/ChatPanel', () => ({
  default: (props: { variant?: string; onOpenVoiceCoachingGrowth?: () => void }) => props.variant === 'page' ? (
    <button type="button" data-testid="open-pilot-growth" onClick={props.onOpenVoiceCoachingGrowth}>查看表达成长</button>
  ) : <div />,
}));

let root: Root;
let host: HTMLDivElement;

async function flush(): Promise<void> {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) as unknown as MediaQueryList;
  window.scrollTo = vi.fn();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  mockServices.discard.mockReset();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

describe('AppShell voice coaching navigation', () => {
  it('opens the same read-only growth view from Interview and Pilot, then hands focus to a new mock draft', async () => {
    await act(async () => root.render(<AppShell />));
    await flush();

    act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-interview"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-ui-growth"]')?.click());
    await flush();
    expect(host.querySelector('[data-testid="voice-growth-view"]')).not.toBeNull();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
    await flush();
    expect(host.querySelector('[data-testid="mock-focus"]')?.textContent).toBe('减少长停顿');
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="mark-voice-saved"]')?.click());
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="close-mock"]')?.click());
    await flush();
    expect(mockServices.discard).not.toHaveBeenCalled();
    expect(host.querySelector('[data-testid="mock-focus"]')).toBeNull();

    act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-pilot"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-pilot-growth"]')?.click());
    await flush();
    expect(host.querySelector('[data-testid="voice-growth-view"]')).not.toBeNull();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
    await flush();
    expect(host.querySelector('[data-testid="mock-focus"]')?.getAttribute('data-attempt-id')).toBe('none');
  });

  it.each(['mark-voice-skipped', 'mark-voice-unknown'])(
    'preserves an already submitted voice answer when closing after %s',
    async (action) => {
      await act(async () => root.render(<AppShell />));
      await flush();
      act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-interview"]')?.click());
      await flush();
      act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-ui-growth"]')?.click());
      await flush();
      act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
      await flush();
      act(() => host.querySelector<HTMLButtonElement>(`[data-testid="${action}"]`)?.click());
      act(() => host.querySelector<HTMLButtonElement>('[data-testid="close-mock"]')?.click());
      await flush();

      expect(mockServices.discard).not.toHaveBeenCalled();
      expect(host.querySelector('[data-testid="mock-focus"]')).toBeNull();
    },
  );

  it('discards a voice transcript that was confirmed locally but never submitted', async () => {
    mockServices.discard.mockResolvedValue(undefined);
    await act(async () => root.render(<AppShell />));
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-interview"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-ui-growth"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="mark-voice-confirmed-only"]')?.click());
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="close-mock"]')?.click());
    await flush();

    expect(mockServices.discard).toHaveBeenCalledWith({ applicationId: 5, eventId: 9, attemptId: 40 });
  });

  it('keeps an unknown voice-save draft when focused practice is opened again for the same event', async () => {
    await act(async () => root.render(<AppShell />));
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-interview"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-ui-growth"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="mark-voice-unknown"]')?.click());
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="close-mock"]')?.click());
    await flush();

    act(() => host.querySelector<HTMLButtonElement>('[data-testid="nav-interview"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="open-ui-growth"]')?.click());
    await flush();
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="practice-growth"]')?.click());
    await flush();

    expect(host.querySelector('[data-testid="mock-focus"]')?.getAttribute('data-attempt-id')).toBe('43');
    expect(mockServices.discard).not.toHaveBeenCalled();
  });
});
