// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  analyzeJD: vi.fn(),
  saveApplicationJdVersion: vi.fn(),
  jdCurrent: null as unknown,
  events: [] as unknown[],
}));

vi.mock('@/services/ai', () => ({ analyzeJD: state.analyzeJD }));
vi.mock('@/services/notes', () => ({
  listNotesByApp: vi.fn().mockResolvedValue([]),
  createNote: vi.fn(),
  deleteNote: vi.fn(),
  updateNote: vi.fn(),
}));
vi.mock('@/services/events', () => ({ listEvents: vi.fn().mockResolvedValue([]) }));
vi.mock('@/services/applicationJdVersions', () => ({
  getCurrentApplicationJd: vi.fn(),
  getApplicationJdVersion: vi.fn(),
  listApplicationJdVersions: vi.fn(),
  saveApplicationJdVersion: state.saveApplicationJdVersion,
}));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: (options: { queryKey?: unknown[] }) => ({
    data: options.queryKey?.[0] === 'events'
      ? state.events
      : options.queryKey?.[0] === 'application-jd-current'
        ? state.jdCurrent
        : null,
    isLoading: false,
  }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('./ApplicationDetail.module.css', () => ({ default: {} }));
vi.mock('./PilotAttachmentHandle', () => ({ createPilotAttachmentDragBinding: () => ({}) }));
vi.mock('./ScheduleEventForm', () => ({ default: () => null }));
vi.mock('./ReviewFormDrawer', () => ({ default: () => null }));
vi.mock('./InterviewReviewProposalDrawer', () => ({ default: () => null }));
vi.mock('./InterviewKnowledgeCaptureDrawer', () => ({
  default: () => null,
  createInterviewKnowledgeCaptureDraft: () => ({}),
}));
vi.mock('./InterviewPreparationProposalDrawer', () => ({ default: () => null }));
vi.mock('./MaterialKitDrawer', () => ({ default: () => null }));
vi.mock('./OpportunityFitReviewDrawer', () => ({ default: () => null }));
vi.mock('./ApplicationOutcomeDrawer', () => ({
  default: (props: { open?: boolean; application?: { company_name?: string } }) => props.open
    ? <div role="dialog">{props.application?.company_name} · 投递事实与结果工作区</div>
    : null,
}));
vi.mock('./NextStepSuggestions', () => ({ default: () => null }));
vi.mock('@ant-design/icons', () => ({
  ArrowLeftOutlined: () => null,
  CalendarOutlined: () => null,
  RobotOutlined: () => null,
  PlusOutlined: () => null,
  AudioOutlined: () => null,
  FileTextOutlined: () => null,
  DatabaseOutlined: () => null,
}));
vi.mock('antd', () => {
  const Form = Object.assign(
    (props: { children: ReactNode; onFinish?: (value: unknown) => void }) => (
      <form onSubmit={(event) => { event.preventDefault(); props.onFinish?.({}); }}>{props.children}</form>
    ),
    { Item: (props: { children: ReactNode }) => <label>{props.children}</label>, useForm: () => [{ resetFields: vi.fn() }] },
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
    Modal: (props: { open?: boolean; title?: ReactNode; cancelText?: ReactNode; children: ReactNode }) => props.open ? (
      <div role="dialog">
        <h3>{props.title}</h3>
        {props.children}
        {props.cancelText && <button type="button">{props.cancelText}</button>}
      </div>
    ) : null,
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
  company_name: '示例公司',
  position_name: '后端工程师',
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
  state.analyzeJD.mockReset();
  state.saveApplicationJdVersion.mockReset();
  state.jdCurrent = null;
  state.events = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
});

describe('ApplicationDetail deterministic Pilot JD entry', () => {
  it('renders the JD editor labels as Chinese text instead of escape sequences', () => {
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));

    const addButton = [...(container?.querySelectorAll('button') ?? [])]
      .find((button) => button.textContent?.includes('\u6dfb\u52a0 JD'));
    expect(addButton).not.toBeUndefined();
    act(() => (addButton as HTMLButtonElement).click());

    const dialog = container?.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain('\u6295\u9012\u5c97\u4f4d\u8d44\u6599');
    expect(dialog?.textContent).toContain('\u53d6\u6d88');
    expect(dialog?.textContent).not.toContain('\\u6295');
    expect(dialog?.querySelector('textarea')?.placeholder).toBe('\u7c98\u8d34\u5c97\u4f4d\u63cf\u8ff0');
    expect(dialog?.querySelector('input')?.placeholder).toBe('\u6765\u6e90 URL\uff08\u4ec5\u5c55\u793a\uff0c\u4e0d\u4f1a\u8bbf\u95ee\uff09');
  });

  it('uses a save shortcut without a current JD and never calls the JD save service', () => {
    const onAskPilot = vi.fn();
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} onAskPilot={onAskPilot} />));

    const shortcut = [...(container?.querySelectorAll('button') ?? [])]
      .find((button) => button.textContent?.includes('保存岗位资料'));
    expect(shortcut).not.toBeUndefined();
    act(() => (shortcut as HTMLButtonElement).click());

    expect(onAskPilot).toHaveBeenCalledWith(application, { type: 'application_jd_save' });
    expect(state.saveApplicationJdVersion).not.toHaveBeenCalled();
    expect(state.analyzeJD).not.toHaveBeenCalled();
  });

  it('uses an update shortcut when a current JD exists', () => {
    state.jdCurrent = { current: { id: 41, jd_text: '已保存 JD', source_url: null } };
    const onAskPilot = vi.fn();
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} onAskPilot={onAskPilot} />));

    const shortcut = [...(container?.querySelectorAll('button') ?? [])]
      .find((button) => button.textContent?.includes('更新岗位资料'));
    expect(shortcut).not.toBeUndefined();
    act(() => (shortcut as HTMLButtonElement).click());

    expect(onAskPilot).toHaveBeenCalledWith(application, { type: 'application_jd_save' });
    expect(state.saveApplicationJdVersion).not.toHaveBeenCalled();
  });

  it('opens the application outcome workspace from the mounted detail view', () => {
    act(() => root?.render(<ApplicationDetail application={application} open onClose={vi.fn()} />));

    const button = [...(container?.querySelectorAll('button') ?? [])]
      .find((candidate) => candidate.textContent?.includes('投递事实与结果'));
    expect(button).not.toBeUndefined();
    act(() => (button as HTMLButtonElement).click());

    expect(container?.querySelector('[role="dialog"]')?.textContent)
      .toContain('示例公司 · 投递事实与结果工作区');
  });
});
