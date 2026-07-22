// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({
  create: vi.fn(),
  deep: vi.fn(),
  get: vi.fn(),
  list: vi.fn(),
  history: [] as Array<{ id: number; recommendation: string; created_at: string }>,
}));

vi.mock('@/services/resumes', () => ({
  listResumes: vi.fn().mockResolvedValue([{ id: 11, name: 'Backend Resume', title: 'Backend Resume' }]),
}));
vi.mock('@/services/opportunityFitReviews', () => ({
  createOpportunityFitReview: state.create,
  createOpportunityFitDeepReview: state.deep,
  getOpportunityFitReview: state.get,
  listOpportunityFitReviews: state.list,
}));
vi.mock('@tanstack/react-query', () => ({
  useQuery: (options: { queryKey?: unknown[]; queryFn: () => unknown }) => ({
    data: options.queryKey?.[0] === 'resumes'
      ? [{ id: 11, name: 'Backend Resume', title: 'Backend Resume' }]
      : state.history,
    isFetching: false,
  }),
  useMutation: (options: { mutationFn: () => unknown; onSuccess?: (data: unknown) => void; onError?: (error: unknown) => void }) => ({
    isPending: false,
    mutate: () => void Promise.resolve(options.mutationFn()).then(options.onSuccess).catch(options.onError),
  }),
}));
vi.mock('antd', () => {
  const Form = Object.assign(
    (props: { children: ReactNode }) => <div>{props.children}</div>,
    { Item: (props: { label?: ReactNode; children: ReactNode }) => <label>{props.label}{props.children}</label> },
  );
  const Input = Object.assign(
    (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
    { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> },
  );
  const Typography = {
    Paragraph: (props: { children: ReactNode }) => <p>{props.children}</p>,
    Text: (props: { children: ReactNode }) => <span>{props.children}</span>,
    Title: (props: { children: ReactNode }) => <h2>{props.children}</h2>,
  };
  return {
    Alert: (props: { message: ReactNode }) => <div role="alert">{props.message}</div>,
    Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{props.children}</button>,
    Card: (props: { title?: ReactNode; children: ReactNode }) => <section><h3>{props.title}</h3>{props.children}</section>,
    Divider: () => <hr />,
    Drawer: (props: { open: boolean; title: ReactNode; children: ReactNode }) => props.open ? <div role="dialog"><h1>{props.title}</h1>{props.children}</div> : null,
    Form,
    Input,
    Select: (props: { value?: unknown; onChange?: (value: unknown) => void; options?: Array<{ value: unknown; label: string }> }) => (
      <select value={String(props.value ?? '')} onChange={(event) => props.onChange?.(Number(event.target.value))}>
        <option value="">select</option>
        {(props.options || []).map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}
      </select>
    ),
    Space: (props: { children: ReactNode }) => <div>{props.children}</div>,
    Spin: () => <span>loading</span>,
    Tag: (props: { children: ReactNode }) => <span>{props.children}</span>,
    Typography,
  };
});

const { default: OpportunityFitReviewDrawer } = await import('./OpportunityFitReviewDrawer');

const application = { id: 7, company_name: 'Example Co.', position_name: 'Backend Engineer' } as never;
let root: Root | undefined;
let container: HTMLDivElement | undefined;

function render(onPrepareMaterials?: (review: unknown, jdText: string) => void) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(<OpportunityFitReviewDrawer application={application} open onClose={vi.fn()} onPrepareMaterials={onPrepareMaterials} />));
  return container;
}

beforeEach(() => {
  state.create.mockReset();
  state.deep.mockReset();
  state.get.mockReset();
  state.list.mockReset();
  state.history = [];
  state.list.mockResolvedValue([]);
  state.create.mockResolvedValue({
    id: 8,
    recommendation: 'hold',
    source: {
      resume: { id: 11, title: 'Backend Resume', sha256: 'resume' },
      jd: { source_label: '用户粘贴 JD', sha256: 'jd', text: 'JD text' },
      candidate_assertions: [],
    },
    triage: {
      summary: { text: 'safe', evidence_refs: [] },
      recommendation: 'hold',
      hard_constraints: [],
      fit_signals: [],
      gaps: [],
      deadline: { status: 'not_stated', text: '', evidence_refs: [] },
      next_questions: ['clarify'],
    },
    deep_review: null,
  });
  state.get.mockResolvedValue({
    id: 8,
    recommendation: 'advance',
    source: {
      resume: { id: 11, title: 'Backend Resume', sha256: 'resume' },
      jd: { source_label: 'Frozen JD', sha256: 'jd', text: 'Frozen JD text' },
      candidate_assertions: [],
    },
    triage: {
      summary: { text: 'safe', evidence_refs: [] },
      recommendation: 'advance',
      hard_constraints: [],
      fit_signals: [],
      gaps: [],
      deadline: { status: 'not_stated', text: '', evidence_refs: [] },
      next_questions: [],
    },
    deep_review: {
      strengths: [],
      gaps_to_address: [],
      questions_to_clarify: [],
      recommended_path: 'prepare_materials',
      next_actions: [],
    },
  });
  vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'd4b4b5e8-0a3a-4a3e-8e4d-6bc7a04d36b0') });
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  vi.unstubAllGlobals();
});

function textareas(view: HTMLDivElement) {
  return [...view.querySelectorAll('textarea')] as HTMLTextAreaElement[];
}

function setValue(element: HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const prototype = element instanceof HTMLSelectElement
    ? HTMLSelectElement.prototype
    : HTMLTextAreaElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

describe('OpportunityFitReviewDrawer', () => {
  it('blocks more than ten assertions before submit', () => {
    const view = render();
    const areas = textareas(view);
    act(() => {
      setValue(areas[1], Array.from({ length: 11 }, (_, index) => `Fact ${index}`).join('\n'));
    });
    expect(view.textContent).toContain('最多填写 10 条非空断言。');
    expect([...view.querySelectorAll('button')].find((button) => button.textContent?.includes('开始 Triage'))?.disabled).toBe(true);
    expect(state.create).not.toHaveBeenCalled();
  });

  it('submits trimmed assertions as independent input', async () => {
    const view = render();
    const areas = textareas(view);
    const select = view.querySelector('select') as HTMLSelectElement;
    act(() => {
      setValue(select, '11');
      setValue(areas[0], 'JD text');
      setValue(areas[1], ' fact one \n\n fact two ');
    });
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      [...view.querySelectorAll('button')].find((button) => button.textContent?.includes('开始 Triage'))?.click();
      await Promise.resolve();
    });
    expect(state.create).toHaveBeenCalledWith(7, expect.objectContaining({
      resume_id: 11,
      jd_text: 'JD text',
      candidate_assertions: ['fact one', 'fact two'],
    }));
  });

  it('hands historical review frozen JD and resume to material preparation', async () => {
    state.history = [{ id: 8, recommendation: 'advance', created_at: '2026-07-21T00:00:00Z' }];
    const onPrepareMaterials = vi.fn();
    const view = render(onPrepareMaterials);

    await act(async () => {
      view.querySelectorAll('button')[0]?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    act(() => {
      const buttons = [...view.querySelectorAll('button')];
      buttons[buttons.length - 1]?.click();
    });

    expect(onPrepareMaterials).toHaveBeenCalledWith(expect.objectContaining({ id: 8 }), 'Frozen JD text');
  });

  it('shows safe mapped copy instead of raw Opportunity Fit errors', async () => {
    state.create.mockRejectedValue({
      response: {
        status: 502,
        data: {
          error_code: 'opportunity_fit_unverifiable',
          error: 'raw provider text',
        },
      },
    });
    const view = render();
    const areas = textareas(view);
    const select = view.querySelector('select') as HTMLSelectElement;
    act(() => {
      setValue(select, '11');
      setValue(areas[0], 'JD text');
    });

    await act(async () => {
      [...view.querySelectorAll('button')].find((button) => button.textContent?.includes('开始 Triage'))?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(view.textContent).toContain('AI 输出未通过证据校验，可重试；原简历已保护，未创建草稿。');
    expect(view.textContent).not.toContain('raw provider text');
  });
});
