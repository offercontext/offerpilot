// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => {
  class InterviewPreparationProposalError extends Error {
    constructor(public status: number, public code: string | null, message = '') {
      super(message);
    }
  }
  return { create: vi.fn(), list: vi.fn(), InterviewPreparationProposalError };
});
vi.mock('@/services/interviewPreparationProposals', () => ({
  createInterviewPreparationProposal: service.create,
  listInterviewPreparationProposals: service.list,
  InterviewPreparationProposalError: service.InterviewPreparationProposalError,
}));

const { default: InterviewPreparationProposalDrawer } = await import('./InterviewPreparationProposalDrawer');

const context = {
  applicationId: 7,
  eventId: 11,
  resumeId: 13,
  jdText: 'Build reliable services.',
  knowledgeSelections: [],
  userAssertions: ['I led a migration.'],
};

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  service.create.mockReset();
  service.list.mockReset();
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

describe('InterviewPreparationProposalDrawer interaction', () => {
  it('requires explicit confirmation and displays a safe empty result in Chinese', async () => {
    service.create.mockResolvedValue({
      id: 20,
      application_id: 7,
      event_id: 11,
      resume_id: 13,
      attempt_status: 'ready',
      proposal_status: 'safe_empty',
      source_status: 'current',
      source_states: { jd: 'not_checked' },
      proposal: {
        preparation_directions: [],
        story_prompts: [],
        review_points: [],
        interviewer_questions: [],
        items_to_clarify: [],
      },
    });

    act(() => root?.render(<InterviewPreparationProposalDrawer open context={context} onClose={() => {}} />));
    const generate = () => [...(container?.querySelectorAll('button') || [])]
      .find((button) => button.textContent === '生成面试准备建议') as HTMLButtonElement;

    expect(container?.textContent).toContain('仅 JD、所选简历和已确认 Knowledge Evidence 会发送给 AI');
    await act(async () => {
      generate().click();
      await Promise.resolve();
    });
    expect(service.create).toHaveBeenCalledWith(expect.objectContaining({
      application_id: 7,
      event_id: 11,
      resume_id: 13,
      user_assertions: ['I led a migration.'],
      idempotency_key: '00000000-0000-0000-0000-000000000001',
    }));
    expect(container?.textContent).toContain('暂无可验证的面试准备建议');
  });

  it('does not claim current sources before JD and resume are selected', () => {
    const emptyContext = { ...context, resumeId: 0, jdText: '' };
    act(() => root?.render(<InterviewPreparationProposalDrawer open context={emptyContext} onClose={() => {}} />));

    expect(container?.textContent).not.toContain('当前使用来源');
  });

  it('maps a provider error without exposing the original message', async () => {
    service.create.mockRejectedValue(new service.InterviewPreparationProposalError(502, 'interview_preparation_provider_error', 'API key secret'));
    act(() => root?.render(<InterviewPreparationProposalDrawer open context={context} onClose={() => {}} />));
    await act(async () => {
      [...(container?.querySelectorAll('button') || [])]
        .find((button) => button.textContent === '生成面试准备建议')
        ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
    });
    expect(container?.textContent).toContain('AI 服务暂不可用，请稍后重试');
    expect(container?.textContent).not.toContain('API key secret');
  });

  it('keeps the same attempt after a Provider 502 and remount', async () => {
    service.create.mockRejectedValueOnce(new service.InterviewPreparationProposalError(502, 'interview_preparation_provider_error'));
    const attemptChanges: Array<{ key: string; result_unknown: boolean } | null> = [];
    const draftChanges: unknown[] = [];
    const props = {
      open: true,
      context,
      onClose: () => {},
      onDraftChange: (draft: unknown) => draftChanges.push(draft),
      onAttemptStateChange: (state: { key: string; result_unknown: boolean } | null) => attemptChanges.push(state),
    };
    act(() => root?.render(<InterviewPreparationProposalDrawer {...props} />));
    await act(async () => {
      container?.querySelectorAll('button')[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
    });
    const unknownAttempt = attemptChanges.find((state) => state?.result_unknown);
    expect(unknownAttempt).toEqual({ key: expect.any(String), result_unknown: true });
    expect(draftChanges).not.toContain(null);
    act(() => root?.render(<InterviewPreparationProposalDrawer {...props} attemptState={unknownAttempt!} />));
    expect(container?.textContent).toContain('上次请求结果待确认，请使用原尝试重试');

    act(() => root?.unmount());
    service.create.mockResolvedValueOnce({
      id: 21,
      application_id: 7,
      event_id: 11,
      resume_id: 13,
      attempt_status: 'ready',
      proposal_status: 'safe_empty',
      source_status: 'current',
      source_states: { jd: 'not_checked' },
      proposal: {
        preparation_directions: [], story_prompts: [], review_points: [],
        interviewer_questions: [], items_to_clarify: [],
      },
    });
    const reusedDraft = {
      attemptState: unknownAttempt!,
      resumeId: 13,
      jdText: context.jdText,
      assertionsText: context.userAssertions.join('\n'),
      knowledgeSelections: [],
    };
    root = createRoot(container!);
    act(() => root?.render(
      <InterviewPreparationProposalDrawer
        {...props}
        attemptState={unknownAttempt!}
        draft={reusedDraft}
      />,
    ));
    await act(async () => {
      container?.querySelectorAll('button')[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
    });
    expect(service.create).toHaveBeenLastCalledWith(expect.objectContaining({
      idempotency_key: unknownAttempt!.key,
    }));
  });

  it('keeps inputs frozen when retry returns 202 generating and remounts with the same key', async () => {
    service.create.mockResolvedValue({
      attempt_status: 'generating',
      application_id: 7,
      event_id: 11,
      idempotency_key: 'unknown-attempt-0001',
      generation_revision: 1,
      retry_after_ms: 1000,
    });
    const attemptState = { key: 'unknown-attempt-0001', result_unknown: true };
    const attemptChanges: Array<{ key: string; result_unknown: boolean } | null> = [];
    const props = {
      open: true,
      context,
      attemptState,
      draft: {
        attemptState,
        resumeId: 13,
        jdText: context.jdText,
        assertionsText: context.userAssertions.join('\n'),
        knowledgeSelections: [],
      },
      onClose: () => {},
      onAttemptStateChange: (state: { key: string; result_unknown: boolean } | null) => attemptChanges.push(state),
    };
    act(() => root?.render(<InterviewPreparationProposalDrawer {...props} />));
    await act(async () => {
      container?.querySelectorAll('button')[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
    });
    expect(attemptChanges[attemptChanges.length - 1]).toEqual(attemptState);
    expect(Array.from(container?.querySelectorAll('select, textarea, input[type="checkbox"]') ?? [])
      .every((control) => (control as HTMLInputElement).disabled)).toBe(true);

    act(() => root?.unmount());
    root = createRoot(container!);
    act(() => root?.render(<InterviewPreparationProposalDrawer {...props} />));
    await act(async () => {
      container?.querySelectorAll('button')[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
    });
    expect(service.create).toHaveBeenLastCalledWith(expect.objectContaining({
      idempotency_key: attemptState.key,
    }));
    expect(Array.from(container?.querySelectorAll('select, textarea, input[type="checkbox"]') ?? [])
      .every((control) => (control as HTMLInputElement).disabled)).toBe(true);
  });

  it('clears the draft and attempt key after a definite validation failure', async () => {
    service.create.mockRejectedValue(new service.InterviewPreparationProposalError(422, 'interview_preparation_inputs_invalid'));
    const draftChanges: unknown[] = [];
    const attemptChanges: unknown[] = [];
    act(() => root?.render(
      <InterviewPreparationProposalDrawer
        open
        context={context}
        onClose={() => {}}
        onDraftChange={(draft) => draftChanges.push(draft)}
        onAttemptStateChange={(state) => attemptChanges.push(state)}
      />,
    ));
    await act(async () => {
      [...(container?.querySelectorAll('button') || [])]
        [0]
        ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(attemptChanges).toContain(null);
    expect(draftChanges).toContain(null);
  });
});
