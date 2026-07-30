import source from './MockInterviewDrawer.tsx?raw';
import { describe, expect, it } from 'vitest';

describe('MockInterviewDrawer safety display contract', () => {
  it('maps failures to fixed Chinese messages without rendering raw errors', () => {
    expect(source).toContain('function safeError(error: unknown)');
    expect(source).toContain('AI 输出未通过验证，请重新开始本次模拟面试。');
    expect(source).toContain('AI 服务暂不可用，结果待确认，请使用原尝试重试。');
    expect(source).not.toContain('error.message');
    expect(source).not.toContain('error.response.data.error');
    expect(source).not.toContain('response.data.error');
  });

  it('cleans deterministic failed attempts before clearing the draft', () => {
    expect(source).toContain('async function clearDefiniteAttempt');
    expect(source).toContain('discardMockInterviewAttempt');
    expect(source).toContain('response?.data?.attempt_id');
    expect(source).toContain('attemptKeyOverride');
    expect(source).toContain('attemptId,');
    expect(source).toContain('attemptKey: currentAttemptKey');
    expect(source).toContain("pendingOperation: 'discard'");
    expect(source).toContain('mock_interview_unverifiable');
  });

  it('clears a pre-attempt 422 without waiting for a DELETE', () => {
    expect(source).toContain('response?.status === 422');
    expect(source).toContain('attemptKey: null');
  });

  it('retains the server Attempt and original key for an unknown start result', () => {
    expect(source).toContain('pendingOperation: \'start\'');
    expect(source).toContain("typeof responseAttemptId === 'number' ? responseAttemptId : draft.attemptId");
    expect(source).toContain('attemptKey,');
  });

  it('treats an already absent Attempt as a successful discard', () => {
    expect(source).toContain('const status = (error as { response?: { status?: number } })?.response?.status;');
    expect(source).toContain('if (status === 404)');
    expect(source).toContain('resetDraft(sourceError);');
  });

  it('records and dispatches each post-start unknown operation', () => {
    expect(source).toContain("pendingOperation?: 'start' | 'answer' | 'question' | 'feedback' | 'confirm' | 'discard';");
    expect(source).toContain("pendingOperation: 'answer'");
    expect(source).toContain("case 'answer': return answer();");
    expect(source).toContain("pendingOperation: 'confirm'");
    expect(source).toContain("case 'confirm': return confirmDraft();");
    expect(source).toContain('turnKey');
    expect(source).toContain('nextQuestionKey');
    expect(source).toContain('feedbackKey');
  });
});
