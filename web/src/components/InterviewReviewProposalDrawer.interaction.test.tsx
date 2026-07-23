// @vitest-environment jsdom
import { act, useState, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const service = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  list: vi.fn(),
}));

vi.mock('@/services/interviewReviewProposals', () => ({
  createInterviewReviewProposal: service.create,
  getInterviewReviewProposal: service.get,
  listInterviewReviewProposals: service.list,
  InterviewReviewProposalError: class InterviewReviewProposalError extends Error {},
}));
vi.mock('./InterviewReviewProposalDrawer.module.css', () => ({ default: {} }));
vi.mock('antd', () => {
  const Typography = {
    Paragraph: ({ children }: { children: ReactNode }) => <p>{children}</p>,
    Text: ({ children }: { children: ReactNode }) => <span>{children}</span>,
    Title: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  };
  const List = Object.assign(
    ({ dataSource, renderItem }: { dataSource: unknown[]; renderItem: (item: unknown) => ReactNode }) => (
      <div>{dataSource.map((item, index) => <div key={index}>{renderItem(item)}</div>)}</div>
    ),
    { Item: ({ children }: { children: ReactNode }) => <div>{children}</div> },
  );
  return {
    Button: ({ children, onClick, disabled }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) => (
      <button type="button" disabled={disabled} onClick={onClick}>{children}</button>
    ),
    Card: ({ title, children }: { title?: ReactNode; children: ReactNode }) => <section><h3>{title}</h3>{children}</section>,
    Empty: ({ description }: { description?: ReactNode }) => <div>{description}</div>,
    List,
    Space: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    Spin: () => <span>loading</span>,
    Tag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
    Typography,
  };
});

const { default: InterviewReviewProposalDrawer } = await import('./InterviewReviewProposalDrawer');

const note = {
  id: 7,
  application_id: 3,
  application_event_id: 9,
  company: 'Example',
  position: 'Engineer',
  round: 'technical',
  date: '2026-07-22',
  questions: 'How do you test?',
  self_reflection: 'I clarified the constraint.',
  difficulty_points: 'The tradeoff was difficult.',
  mood: 'focused',
} as never;

let root: Root | undefined;
let container: HTMLDivElement | undefined;

function Harness() {
  const [open, setOpen] = useState(true);
  const [attemptState, setAttemptState] = useState<{ key: string; result_unknown: boolean; event_id: number | null } | null>(null);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>重新打开</button>
      <button type="button" onClick={() => setOpen(false)}>切换页面</button>
      {open && (
        <InterviewReviewProposalDrawer
          open
          note={note}
          eventID={9}
          attemptState={attemptState}
          onAttemptStateChange={setAttemptState}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

beforeEach(() => {
  service.create.mockReset();
  service.get.mockReset();
  service.list.mockResolvedValue([]);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('00000000-0000-0000-0000-000000000001');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  vi.restoreAllMocks();
});

describe('InterviewReviewProposalDrawer attempt ownership', () => {
  it('reuses the unknown attempt key after close and reopen', async () => {
    service.create.mockRejectedValueOnce(new Error('network disconnected'));
    service.create.mockResolvedValueOnce({
      id: 20,
      created_at: '2026-07-22T00:00:00Z',
      source_status: 'current',
      proposal: {
        summary: { text: 'safe', evidence_refs: [] },
        observations: [],
        clarifications: [],
        practice_focuses: [],
        next_questions: [],
      },
    });

    act(() => root?.render(<Harness />));
    const generate = () => [...(container?.querySelectorAll('button') || [])]
      .find((button) => button.textContent === '生成复盘建议') as HTMLButtonElement;

    await act(async () => {
      generate().click();
      await Promise.resolve();
    });
    expect(service.create).toHaveBeenLastCalledWith(7, '00000000-0000-0000-0000-000000000001');

    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '关闭')
        ?.click();
    });
    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '重新打开')
        ?.click();
    });
    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      generate().click();
      await Promise.resolve();
    });

    expect(service.create).toHaveBeenNthCalledWith(2, 7, '00000000-0000-0000-0000-000000000001');
  });

  it('creates a new key after a successful response and reopening', async () => {
    service.create.mockResolvedValue({
      id: 20,
      created_at: '2026-07-22T00:00:00Z',
      source_status: 'current',
      proposal: {
        summary: { text: 'safe', evidence_refs: [] },
        observations: [],
        clarifications: [],
        practice_focuses: [],
        next_questions: [],
      },
    });
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValueOnce('00000000-0000-0000-0000-000000000001')
      .mockReturnValueOnce('00000000-0000-0000-0000-000000000002');

    act(() => root?.render(<Harness />));
    const generate = () => [...(container?.querySelectorAll('button') || [])]
      .find((button) => button.textContent === '生成复盘建议') as HTMLButtonElement;
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });
    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '关闭')
        ?.click();
    });
    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '重新打开')
        ?.click();
    });
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });

    expect(service.create).toHaveBeenNthCalledWith(2, 7, '00000000-0000-0000-0000-000000000002');
  });

  it('keeps the key when the parent unmounts during a pending request', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined;
    service.create.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    service.create.mockResolvedValueOnce({
      id: 20,
      created_at: '2026-07-22T00:00:00Z',
      source_status: 'current',
      proposal: {
        summary: { text: 'safe', evidence_refs: [] },
        observations: [],
        clarifications: [],
        practice_focuses: [],
        next_questions: [],
      },
    });

    act(() => root?.render(<Harness />));
    const generate = () => [...(container?.querySelectorAll('button') || [])]
      .find((button) => button.textContent === '生成复盘建议') as HTMLButtonElement;
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });
    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '切换页面')
        ?.click();
    });
    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '重新打开')
        ?.click();
    });
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });

    expect(service.create).toHaveBeenNthCalledWith(2, 7, '00000000-0000-0000-0000-000000000001');
    act(() => { resolveFirst?.({}); });
  });

  it('renders a safe empty proposal as a normal empty state', async () => {
    service.create.mockResolvedValueOnce({
      id: 20,
      created_at: '2026-07-22T00:00:00Z',
      source_status: 'current',
      proposal: {
        summary: { text: '暂无可验证建议', evidence_refs: [] },
        observations: [],
        clarifications: [],
        practice_focuses: [],
        next_questions: [],
      },
    });

    act(() => root?.render(<Harness />));
    const generate = () => {
      const buttons = [...(container?.querySelectorAll('button') || [])];
      return buttons[buttons.length - 1] as HTMLButtonElement;
    };
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });

    expect(container?.textContent).toContain('暂无可验证建议');
    expect(container?.querySelector('[role="alert"]')).toBeNull();
  });
});
