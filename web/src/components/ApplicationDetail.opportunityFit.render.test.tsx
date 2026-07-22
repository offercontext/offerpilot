// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writeMaterialKitHandoff } from '@/features/pilot/materialKitHandoff';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  materialProps: vi.fn(),
  analyzeJD: vi.fn(),
}));

vi.mock('@/services/ai', () => ({ analyzeJD: state.analyzeJD }));
vi.mock('@/services/notes', () => ({
  listNotesByApp: vi.fn().mockResolvedValue([]),
  createNote: vi.fn(),
  deleteNote: vi.fn(),
  updateNote: vi.fn(),
}));
vi.mock('@/services/events', () => ({ listEvents: vi.fn().mockResolvedValue([]) }));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: (options: { queryKey?: unknown[] }) => ({
    data: options.queryKey?.[0] === 'notes' || options.queryKey?.[0] === 'events' ? [] : [],
    isLoading: false,
  }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('./ApplicationDetail.module.css', () => ({ default: {} }));
vi.mock('./PilotAttachmentHandle', () => ({ createPilotAttachmentDragBinding: () => ({}) }));
vi.mock('./ScheduleEventForm', () => ({ default: () => null }));
vi.mock('./ReviewFormDrawer', () => ({ default: () => null }));
vi.mock('./MaterialKitDrawer', () => ({
  default: (props: { initialResumeID?: number; initialJdSnapshot?: string; onClose?: () => void }) => {
    state.materialProps(props);
    return (
      <div data-testid="material-kit" data-resume-id={props.initialResumeID} data-jd={props.initialJdSnapshot}>
        <button type="button" aria-label="close material kit" onClick={props.onClose}>close</button>
      </div>
    );
  },
}));
vi.mock('./OpportunityFitReviewDrawer', () => ({
  default: (props: { onPrepareMaterials: (review: unknown, jdText: string) => void }) => (
    <button onClick={() => props.onPrepareMaterials({ source: { resume: { id: 11 } } }, 'Frozen JD text')}>
      prepare
    </button>
  ),
}));
vi.mock('@ant-design/icons', () => ({
  ArrowLeftOutlined: () => null,
  CalendarOutlined: () => null,
  RobotOutlined: () => null,
  PlusOutlined: () => null,
  AudioOutlined: () => null,
  FileTextOutlined: () => null,
}));
vi.mock('antd', () => {
  const Form = Object.assign(
    (props: { children: ReactNode; onFinish?: (value: unknown) => void }) => <form onSubmit={(event) => { event.preventDefault(); props.onFinish?.({}); }}>{props.children}</form>,
    {
      Item: (props: { children: ReactNode }) => <label>{props.children}</label>,
      useForm: () => [{ resetFields: vi.fn() }],
    },
  );
  const Input = Object.assign(
    (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
    { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> },
  );
  const Typography = {
    Title: (props: { children: ReactNode }) => <h2>{props.children}</h2>,
    Paragraph: (props: { children: ReactNode }) => <p>{props.children}</p>,
    Text: (props: { children: ReactNode }) => <span>{props.children}</span>,
  };
  return {
    Button: ({ children, htmlType: _htmlType, loading: _loading, icon: _icon, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { htmlType?: string; loading?: boolean; icon?: ReactNode }) => (
      <button {...props}>{children}</button>
    ),
    Divider: () => <hr />,
    Empty: (props: { description?: ReactNode }) => <div>{props.description}</div>,
    Form,
    Input,
    Popconfirm: (props: { children: ReactNode }) => <>{props.children}</>,
    Select: () => <select />,
    Space: (props: { children: ReactNode }) => <div>{props.children}</div>,
    Spin: () => <span>loading</span>,
    Tag: (props: { children: ReactNode }) => <span>{props.children}</span>,
    Timeline: () => null,
    Typography,
    message: { success: vi.fn(), error: vi.fn() },
  };
});

const { default: ApplicationDetail } = await import('./ApplicationDetail');

const application = {
  id: 7,
  company_name: 'Example Co.',
  position_name: 'Backend Engineer',
  job_url: 'https://external.example/job/7',
  status: 'pending',
  source: 'manual',
  notes: '',
  applied_at: '2026-07-21T00:00:00Z',
  created_at: '2026-07-21T00:00:00Z',
  updated_at: '2026-07-21T00:00:00Z',
} as never;

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  state.materialProps.mockReset();
  state.analyzeJD.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
});

describe('ApplicationDetail opportunity fit handoff', () => {
  it('passes historical frozen Resume and JD into Material Kit without opening a URL', () => {
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));

    expect(container?.querySelector('a')).toBeNull();
    expect(state.analyzeJD).not.toHaveBeenCalled();

    act(() => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '岗位决策漏斗')
        ?.click();
    });
    act(() => container?.querySelector('button')?.click());

    const materialKit = container?.querySelector('[data-testid="material-kit"]');
    expect(materialKit?.getAttribute('data-resume-id')).toBe('11');
    expect(materialKit?.getAttribute('data-jd')).toBe('Frozen JD text');
  });

  it('consumes a matching AppShell handoff once and uses frozen values', async () => {
    writeMaterialKitHandoff({
      applicationId: 7,
      resumeId: 12,
      jdText: 'Frozen Pilot JD',
      resumeEvidenceProof: { resumeId: 12, sha256: 'hash', contentJson: { raw_text: 'resume' } },
    });

    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));
    await act(async () => {
      await Promise.resolve();
    });

    expect(container?.querySelector('[data-testid="material-kit"]')?.getAttribute('data-resume-id')).toBe('12');
    expect(container?.querySelector('[data-testid="material-kit"]')?.getAttribute('data-jd')).toBe('Frozen Pilot JD');
  });

  it('clears consumed material prefill when switching to another Application', async () => {
    writeMaterialKitHandoff({
      applicationId: 7,
      resumeId: 12,
      jdText: 'Frozen Pilot JD',
      resumeEvidenceProof: { resumeId: 12, sha256: 'hash', contentJson: { raw_text: 'resume' } },
    });
    const otherApplication = Object.assign({}, application, { id: 8 }) as typeof application;

    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));
    await act(async () => { await Promise.resolve(); });
    expect(container?.querySelector('[data-testid="material-kit"]')).not.toBeNull();

    act(() => root?.render(<ApplicationDetail application={otherApplication} open onClose={vi.fn()} />));
    await act(async () => { await Promise.resolve(); });
    expect(container?.querySelector('[data-testid="material-kit"]')).toBeNull();
  });

  it('clears the consumed material prefill immediately when Material Kit closes', async () => {
    writeMaterialKitHandoff({
      applicationId: 7,
      resumeId: 12,
      jdText: 'Frozen Pilot JD',
      resumeEvidenceProof: { resumeId: 12, sha256: 'hash', contentJson: { raw_text: 'resume' } },
    });

    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));
    await act(async () => { await Promise.resolve(); });
    expect(container?.querySelector('[data-testid="material-kit"]')).not.toBeNull();

    act(() => {
      (container?.querySelector('[aria-label="close material kit"]') as HTMLButtonElement)?.click();
    });

    expect(container?.querySelector('[data-testid="material-kit"]')).toBeNull();
    expect(state.materialProps.mock.calls[state.materialProps.mock.calls.length - 1]?.[0]).toMatchObject({
      initialResumeID: 12,
      initialJdSnapshot: 'Frozen Pilot JD',
    });
  });

  it('exposes the Application-scoped Pilot evaluation entry without URL analysis', () => {
    const openPilot = vi.fn();
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} onOpenPilotOpportunityFit={openPilot} />));
    const button = [...(container?.querySelectorAll('button') || [])]
      .find((candidate) => candidate.textContent === '在 Pilot 中评估');
    act(() => button?.click());
    expect(openPilot).toHaveBeenCalledWith(application);
    expect(state.analyzeJD).not.toHaveBeenCalled();
  });
});
