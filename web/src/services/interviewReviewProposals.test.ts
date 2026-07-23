import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiGet, apiPost, createApiClient } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  createApiClient: vi.fn(),
}));

vi.mock('./http', () => ({ createApiClient }));
createApiClient.mockReturnValue({ get: apiGet, post: apiPost });

const { createInterviewReviewProposal, listInterviewReviewProposals } = await import(
  './interviewReviewProposals'
);

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('interview review proposal service', () => {
  it('uses the proposal API contract', async () => {
    apiPost.mockResolvedValue({ data: { id: 3 } });
    apiGet.mockResolvedValue({ data: [] });

    await expect(createInterviewReviewProposal(7, 'attempt-1')).resolves.toEqual({ id: 3 });
    await expect(listInterviewReviewProposals(7)).resolves.toEqual([]);

    expect(apiPost).toHaveBeenCalledWith('/notes/7/interview-review-proposals', {
      idempotency_key: 'attempt-1',
    });
    expect(apiGet).toHaveBeenCalledWith('/notes/7/interview-review-proposals');
  });

  it.each([
    ['interview_review_event_required', '请先绑定有效的面试事件。'],
    ['interview_review_not_found', '面试复盘已不可见，请重新打开投递。'],
    ['interview_review_source_conflict', '复盘来源已变化，请重新核对后再生成。'],
    ['interview_review_provider_error', 'AI 服务暂不可用，请稍后重试。'],
    ['interview_review_unverifiable', 'AI 建议未通过证据校验，原复盘未受影响，请重试。'],
  ])('maps %s without exposing server text', async (code, message) => {
    apiPost.mockRejectedValue({
      response: { status: 502, data: { error_code: code, error: 'secret server detail' } },
      message: 'Axios secret',
    });

    await expect(createInterviewReviewProposal(7, 'attempt-1')).rejects.toMatchObject({ message });
    await expect(createInterviewReviewProposal(7, 'attempt-1')).rejects.not.toThrow('secret');
  });

  it('uses a neutral fallback for unknown failures', async () => {
    apiPost.mockRejectedValue(new Error('raw internal error'));

    await expect(createInterviewReviewProposal(7, 'attempt-1')).rejects.toMatchObject({
      message: '复盘建议暂时不可用，请稍后重试。',
    });
  });

  it('keeps a bare 502 distinguishable as an unknown result', async () => {
    apiPost.mockRejectedValue({
      response: { status: 502, data: { error: 'provider detail' } },
      message: 'Axios provider detail',
    });

    const error = await createInterviewReviewProposal(7, 'attempt-1').catch((cause) => cause);

    expect(error).toMatchObject({ message: 'AI 服务暂不可用，请稍后重试。' });
    expect(error).toMatchObject({ code: undefined });
  });
});
