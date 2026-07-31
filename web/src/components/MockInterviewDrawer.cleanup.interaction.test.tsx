// @vitest-environment jsdom
import { act, type ReactNode, useRef, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MockInterviewDrawerDraft } from './MockInterviewDrawer';

const services = vi.hoisted(() => ({
  startMockInterview: vi.fn(),
  generateMockInterviewQuestion: vi.fn(),
  submitMockInterviewAnswer: vi.fn(),
  finishMockInterview: vi.fn(),
  discardMockInterviewAttempt: vi.fn(),
  listMockInterviewHistory: vi.fn(),
  confirmMockInterviewReviewDraft: vi.fn(),
  listInterviewPreparationProposals: vi.fn(),
}));

vi.mock('@/services/mockInterviews', () => services);
vi.mock('@/services/interviewPreparationProposals', () => ({
  listInterviewPreparationProposals: services.listInterviewPreparationProposals,
}));
vi.mock('antd', () => ({
  Alert: (props: { children?: ReactNode; action?: ReactNode }) => <div>{props.children}{props.action}</div>,
  Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props} />,
  Drawer: (props: { open?: boolean; children?: ReactNode; onClose?: () => void }) => (
    props.open ? <div role="dialog">{props.children}<button type="button" data-testid="close-drawer" onClick={props.onClose}>close</button></div> : null
  ),
  Empty: (props: { description?: ReactNode }) => <div>{props.description}</div>,
  Input: Object.assign(
    (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
    { TextArea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} /> },
  ),
  List: (props: { dataSource?: unknown[]; renderItem: (item: never) => ReactNode }) => (
    <div>{(props.dataSource ?? []).map((item, index) => <div key={index}>{props.renderItem(item as never)}</div>)}</div>
  ),
  Select: (props: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...props} />,
  Space: (props: { children?: ReactNode }) => <div>{props.children}</div>,
  Spin: () => <span>loading</span>,
  Tag: (props: { children?: ReactNode }) => <span>{props.children}</span>,
}));

const { default: MockInterviewDrawer } = await import('./MockInterviewDrawer');

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const baseDraft: MockInterviewDrawerDraft = {
  jdText: 'JD',
  attemptKey: null,
  questionKey: null,
  feedbackKey: null,
  turnKey: null,
  nextQuestionKey: null,
  confirmationKey: null,
  answerSubmitted: false,
  editedBlocks: {},
  preparationItemIds: [],
  attemptId: null,
  turnNo: 1,
  question: '',
  answer: '',
  proposalId: null,
  proposal: null,
  selectedIds: [],
  resultUnknown: false,
  error: null,
};

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function drawerButtons(): HTMLButtonElement[] {
  return [...(container?.querySelectorAll('button') ?? [])]
    .filter((button) => !button.dataset.testid) as HTMLButtonElement[];
}

function flush() {
  return act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function Harness({ initial = baseDraft }: { initial?: MockInterviewDrawerDraft }) {
  const [open, setOpen] = useState(true);
  const [draft, setDraft] = useState(initial);
  const draftRef = useRef(initial);
  const patches = useRef<Partial<MockInterviewDrawerDraft>[]>([]);
  return (
    <>
      <button type="button" data-testid="toggle-drawer" onClick={() => setOpen((value) => !value)}>toggle</button>
      {open ? (
        <MockInterviewDrawer
          open
          applicationId={7}
          eventId={11}
          resumes={[{ id: 3, title: 'Resume' }]}
          draft={draft}
          onDraftChange={(patch) => {
            patches.current.push(patch);
            setDraft((current) => {
              const next = { ...current, ...patch };
              draftRef.current = next;
              return next;
            });
          }}
          onClose={() => setOpen(false)}
        />
      ) : null}
      <output data-testid="draft-state">{JSON.stringify(draftRef.current)}</output>
    </>
  );
}

function render(initial?: MockInterviewDrawerDraft) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(<Harness initial={initial} />));
}

async function retryDiscardAfterRemount() {
  act(() => (container?.querySelector('[data-testid="toggle-drawer"]') as HTMLButtonElement).click());
  act(() => (container?.querySelector('[data-testid="toggle-drawer"]') as HTMLButtonElement).click());
  await flush();
  act(() => drawerButtons()[0]?.click());
  await flush();
}

beforeEach(() => {
  services.startMockInterview.mockReset();
  services.generateMockInterviewQuestion.mockReset();
  services.submitMockInterviewAnswer.mockReset();
  services.finishMockInterview.mockReset();
  services.discardMockInterviewAttempt.mockReset();
  services.listMockInterviewHistory.mockResolvedValue([]);
  services.listInterviewPreparationProposals.mockResolvedValue([]);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('MockInterviewDrawer failed-attempt cleanup', () => {
  it('preserves the initial Attempt ID/key across DELETE unknown, remount, and retry', async () => {
    const failure = { response: { status: 502, data: { error_code: 'mock_interview_unverifiable', attempt_id: 101 } } };
    services.startMockInterview.mockRejectedValue(failure);
    services.discardMockInterviewAttempt
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockResolvedValueOnce(undefined);
    render({ ...baseDraft, resumeId: 3 });

    act(() => drawerButtons()[0]?.click());
    await flush();
    const originalKey = services.startMockInterview.mock.calls[0][0].attemptKey as string;
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: 101,
      attemptKey: originalKey,
      pendingOperation: 'discard',
    });

    await retryDiscardAfterRemount();
    expect(services.discardMockInterviewAttempt).toHaveBeenNthCalledWith(2, {
      applicationId: 7,
      eventId: 11,
      attemptId: 101,
    });
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: null,
      attemptKey: null,
      resultUnknown: false,
    });
  });

  it('retains the original key and server Attempt after an unknown Provider result', async () => {
    services.startMockInterview.mockRejectedValue({
      response: { status: 502, data: { error_code: 'mock_interview_provider_error', attempt_id: 202 } },
    });
    render({ ...baseDraft, resumeId: 3 });

    act(() => drawerButtons()[0]?.click());
    await flush();
    const originalKey = services.startMockInterview.mock.calls[0][0].attemptKey as string;
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: 202,
      attemptKey: originalKey,
      pendingOperation: 'start',
      resultUnknown: true,
    });
    expect(services.discardMockInterviewAttempt).not.toHaveBeenCalled();
  });

  it('does not claim current sources before a resume and JD are present', () => {
    render({ ...baseDraft, jdText: '', resumeId: undefined });

    expect(container?.textContent).not.toContain('当前使用来源');
  });

  it.each([
    ['answer', { attemptId: 301, attemptKey: 'answer-attempt', answer: 'answer' }, 0],
    ['next question', { attemptId: 302, attemptKey: 'question-attempt', answer: 'answer', answerSubmitted: true }, 2],
    ['feedback', { attemptId: 303, attemptKey: 'feedback-attempt', answer: 'answer', answerSubmitted: true }, 1],
  ])('cleans a deterministic %s failure only after DELETE is retried', async (_operation, patch, buttonIndex) => {
    const operation = _operation === 'answer'
      ? services.submitMockInterviewAnswer
      : _operation === 'next question'
        ? services.generateMockInterviewQuestion
        : services.finishMockInterview;
    operation.mockRejectedValue({ response: { status: 502, data: { error_code: 'mock_interview_unverifiable' } } });
    services.discardMockInterviewAttempt
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockResolvedValueOnce(undefined);
    render({ ...baseDraft, ...patch });

    act(() => drawerButtons()[buttonIndex]?.click());
    await flush();
    expect(services.discardMockInterviewAttempt).toHaveBeenCalledWith({
      applicationId: 7,
      eventId: 11,
      attemptId: patch.attemptId,
    });
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: patch.attemptId,
      attemptKey: patch.attemptKey,
      pendingOperation: 'discard',
      resultUnknown: true,
    });

    await retryDiscardAfterRemount();
    expect(services.discardMockInterviewAttempt).toHaveBeenCalledTimes(2);
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: null,
      attemptKey: null,
      resultUnknown: false,
    });
  });

  it('clears a pre-attempt 422 without issuing DELETE', async () => {
    services.startMockInterview.mockRejectedValue({ response: { status: 422, data: { error_code: 'mock_interview_event_required' } } });
    render({ ...baseDraft, resumeId: 3 });

    act(() => drawerButtons()[0]?.click());
    await flush();
    expect(services.discardMockInterviewAttempt).not.toHaveBeenCalled();
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: null,
      attemptKey: null,
      resultUnknown: false,
    });
  });

  it('treats DELETE 404 as an already-completed cleanup', async () => {
    services.submitMockInterviewAnswer.mockRejectedValue({
      response: { status: 502, data: { error_code: 'mock_interview_unverifiable' } },
    });
    services.discardMockInterviewAttempt.mockRejectedValue({ response: { status: 404 } });
    render({ ...baseDraft, attemptId: 404, attemptKey: 'attempt-404', answer: 'answer' });

    act(() => drawerButtons()[0]?.click());
    await flush();
    expect(services.discardMockInterviewAttempt).toHaveBeenCalledTimes(1);
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: null,
      attemptKey: null,
      resultUnknown: false,
    });
  });

  it('replays an unknown confirmation after remount with the same key and selected blocks', async () => {
    services.confirmMockInterviewReviewDraft
      .mockRejectedValueOnce({ response: { status: 502, data: { error_code: 'mock_interview_provider_error' } } })
      .mockResolvedValueOnce({ draft_id: 77, status: 'confirmed' });
    const proposal = {
      schema_version: '1',
      proposal_status: 'normal' as const,
      strengths: [{ id: 'strength-1', text: 'Clear answer', evidence_refs: [{ source: 'turn', path: '/turns/001/answer', excerpt: 'answer' }] }],
      practice_points: [],
      follow_up_questions: [],
      next_practice_steps: [],
    };
    render({
      ...baseDraft,
      attemptId: 700,
      attemptKey: 'attempt-700',
      proposalId: 701,
      proposal,
      selectedIds: ['strength-1'],
    });

    act(() => drawerButtons()[0]?.click());
    await flush();
    act(() => drawerButtons()[0]?.click());
    await flush();
    const firstRequest = services.confirmMockInterviewReviewDraft.mock.calls[0][0];
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: 700,
      confirmationKey: firstRequest.confirmationKey,
      pendingOperation: 'confirm',
      resultUnknown: true,
    });
    expect([...container?.querySelectorAll('input, textarea') ?? []].every((control) => (control as HTMLInputElement).disabled)).toBe(true);
    expect(drawerButtons().slice(1).every((button) => button.disabled)).toBe(true);
    drawerButtons().slice(1).forEach((button) => button.click());
    await flush();
    expect(services.confirmMockInterviewReviewDraft).toHaveBeenCalledTimes(1);

    await retryDiscardAfterRemount();
    const secondRequest = services.confirmMockInterviewReviewDraft.mock.calls[1][0];
    expect(secondRequest.confirmationKey).toBe(firstRequest.confirmationKey);
    expect(secondRequest.selectedBlocks).toEqual(firstRequest.selectedBlocks);
    const finalDraft = JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}');
    expect(finalDraft).toMatchObject({ resultUnknown: false });
    expect(finalDraft).not.toHaveProperty('pendingOperation');
  });

  it.each([
    ['answer', { attemptId: 501, attemptKey: 'answer-attempt', answer: 'answer' }, services.submitMockInterviewAnswer],
    ['question', { attemptId: 502, attemptKey: 'question-attempt', answer: 'answer', answerSubmitted: true }, services.generateMockInterviewQuestion],
    ['feedback', { attemptId: 503, attemptKey: 'feedback-attempt', answer: 'answer', answerSubmitted: true }, services.finishMockInterview],
  ])('retries an unknown %s result through the same endpoint and key after remount', async (_operation, patch, operation) => {
    operation
      .mockRejectedValueOnce({ response: { status: 502, data: { error_code: 'mock_interview_provider_error', attempt_id: patch.attemptId } } })
      .mockResolvedValueOnce(_operation === 'answer'
        ? { attempt_id: patch.attemptId, attempt_status: 'in_progress', transcript_fingerprint: 'fingerprint' }
        : _operation === 'question'
          ? { attempt_id: patch.attemptId, turn: { turn_no: 2, question: 'Next question', answer: '' } }
          : {
            attempt_id: patch.attemptId,
            proposal_id: 9,
            proposal: {
              proposal_status: 'safe_empty',
              strengths: [],
              practice_points: [],
              follow_up_questions: [],
              next_practice_steps: [],
            },
          });
    render({ ...baseDraft, ...patch });

    const initialButtonIndex = _operation === 'answer' ? 0 : _operation === 'question' ? 2 : 1;
    act(() => drawerButtons()[initialButtonIndex]?.click());
    await flush();
    const firstRequest = operation.mock.calls[0][0];
    const expectedKey = _operation === 'answer'
      ? firstRequest.turnKey
      : _operation === 'question'
        ? firstRequest.questionKey
        : firstRequest.feedbackKey;
    expect(JSON.parse(container?.querySelector('[data-testid="draft-state"]')?.textContent ?? '{}')).toMatchObject({
      attemptId: patch.attemptId,
      pendingOperation: _operation,
      resultUnknown: true,
    });
    expect([...container?.querySelectorAll('textarea') ?? []].every((textarea) => textarea.disabled)).toBe(true);
    expect(drawerButtons().slice(1).every((button) => button.disabled)).toBe(true);
    drawerButtons().slice(1).forEach((button) => button.click());
    await flush();
    expect(operation).toHaveBeenCalledTimes(1);

    await retryDiscardAfterRemount();
    const retryRequest = operation.mock.calls[1][0];
    expect(operation).toHaveBeenCalledTimes(2);
    expect(retryRequest).toMatchObject({
      attemptId: patch.attemptId,
      ...(_operation === 'answer' ? { turnKey: expectedKey } : {}),
      ...(_operation === 'question' ? { questionKey: expectedKey } : {}),
      ...(_operation === 'feedback' ? { feedbackKey: expectedKey } : {}),
    });
    expect(services.startMockInterview).not.toHaveBeenCalled();
  });
});
