// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ create: vi.fn(), list: vi.fn() }));
vi.mock('@/services/interviewPreparationProposals', () => ({
  createInterviewPreparationProposal: service.create,
  listInterviewPreparationProposals: service.list,
  InterviewPreparationProposalError: class InterviewPreparationProposalError extends Error {
    status = 502;
    code = 'interview_preparation_provider_error';
  },
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

  it('maps a provider error without exposing the original message', async () => {
    service.create.mockRejectedValue({ status: 502, code: 'interview_preparation_provider_error', message: 'API key secret' });
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
});
