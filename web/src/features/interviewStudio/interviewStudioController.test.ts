import { describe, expect, it } from 'vitest';
import {
  createStudioState,
  reduceStudioState,
  shouldGenerateNextQuestion,
  type StudioState,
} from './interviewStudioController';

describe('interview studio controller', () => {
  it('keeps text and voice on the same confirmed-answer lifecycle', () => {
    let state = createStudioState({ turnNo: 1, question: '请介绍一次故障排查。' });
    state = reduceStudioState(state, { type: 'answer_mode', mode: 'voice' });
    state = reduceStudioState(state, { type: 'draft_changed', answer: '我先看指标，再缩小范围。' });
    state = reduceStudioState(state, { type: 'transcript_confirmed' });
    expect(state.phase).toBe('answering');
    state = reduceStudioState(state, { type: 'answer_submitting', turnKey: 'turn-001' });
    state = reduceStudioState(state, { type: 'answer_succeeded' });
    expect(state.phase).toBe('next_question_generating');
    expect(state.pendingOperation).toBe('question');
    expect(shouldGenerateNextQuestion({ ...state, phase: 'answer_confirmed' })).toBe(true);
  });

  it('freezes the original key and answer when a request result is unknown', () => {
    const state = createStudioState({ turnNo: 2, question: '你如何验证修复？' });
    const answering = reduceStudioState(state, { type: 'draft_changed', answer: '我会补充回归指标。' });
    const submitting = reduceStudioState(answering, { type: 'answer_submitting', turnKey: 'turn-002' });
    const unknown = reduceStudioState(submitting, { type: 'result_unknown', operation: 'answer', message: '结果待确认' });
    expect(unknown.phase).toBe('result_unknown');
    expect(unknown.answer).toBe('我会补充回归指标。');
    expect(unknown.turnKey).toBe('turn-002');
    expect(unknown.pendingOperation).toBe('answer');
  });

  it('clears result-unknown state when retrying the frozen answer key', () => {
    const state = createStudioState({ turnNo: 1, question: 'retry question' });
    const unknown = reduceStudioState(
      reduceStudioState(
        reduceStudioState(state, { type: 'draft_changed', answer: 'confirmed answer' }),
        { type: 'answer_submitting', turnKey: 'turn-retry' },
      ),
      { type: 'result_unknown', operation: 'answer', message: 'unknown result' },
    );
    const retrying = reduceStudioState(unknown, { type: 'answer_submitting', turnKey: unknown.turnKey ?? 'turn-retry' });

    expect(retrying.resultUnknown).toBe(false);
    expect(retrying.turnKey).toBe('turn-retry');
    expect(retrying.pendingOperation).toBe('answer');
  });

  it('stops automatic question generation after the fifth confirmed turn', () => {
    const state: StudioState = { ...createStudioState({ turnNo: 5, question: '最后一个问题？' }), phase: 'answer_confirmed' };
    expect(shouldGenerateNextQuestion(state)).toBe(false);
    expect(reduceStudioState(state, { type: 'answer_succeeded' }).phase).toBe('completed');
  });
});
