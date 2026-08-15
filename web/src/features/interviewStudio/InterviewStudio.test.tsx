// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContinuousVoiceModePanel from './ContinuousVoiceModePanel';
import InterviewStudio from './InterviewStudio';

const serviceSpies = vi.hoisted(() => ({
  start: vi.fn(),
  answer: vi.fn(),
  nextQuestion: vi.fn(),
  finish: vi.fn(),
  saveVoiceReview: vi.fn(),
}));

vi.mock('@/services/mockInterviews', () => ({
  startInterviewStudioAttempt: serviceSpies.start,
  submitInterviewStudioAnswer: serviceSpies.answer,
  generateInterviewStudioQuestion: serviceSpies.nextQuestion,
  finishInterviewStudio: serviceSpies.finish,
}));

vi.mock('@/services/voiceCoaching', () => ({
  saveInterviewStudioVoiceCoachingSnapshot: serviceSpies.saveVoiceReview,
}));

vi.mock('@/features/mockInterviewVoice/VoiceAnswerComposer', () => ({
  default: (props: {
    continuousCommand?: { id: number; type: string };
    onContinuousEvent?: (event: { type: string; commandId: number; message?: string }) => void;
    onVoiceReviewConfirmed?: (text: string, summary: unknown) => void;
  }) => {
    React.useEffect(() => {
      const command = props.continuousCommand;
      if (!command) return;
      if (command.type === 'preflight') props.onContinuousEvent?.({ type: 'preflight_succeeded', commandId: command.id });
      if (command.type === 'read_question') props.onContinuousEvent?.({ type: 'question_read_finished', commandId: command.id });
      if (command.type === 'start_recording') props.onContinuousEvent?.({ type: 'recording_started', commandId: command.id });
      if (command.type === 'stop_recording') {
        props.onContinuousEvent?.({ type: 'recording_stopped', commandId: command.id });
        props.onContinuousEvent?.({ type: 'review_available', commandId: command.id });
      }
    }, [props.continuousCommand, props.onContinuousEvent]);
    return <button type="button" onClick={() => props.onVoiceReviewConfirmed?.('我先定位日志，再完成回滚。', {
      totalDurationMs: 1000,
      voicedDurationMs: 800,
      pauseCount: 1,
      longestPauseMs: 200,
      speechRateCpm: 120,
      fillerOccurrences: [],
    } as never)}>确认录音文字</button>;
  },
}));

let root: Root | undefined;
let host: HTMLDivElement | undefined;

async function renderPanel(props: Partial<React.ComponentProps<typeof ContinuousVoiceModePanel>> = {}) {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root!.render(<ContinuousVoiceModePanel status="disabled" onEnable={vi.fn()} {...props} />);
  });
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(host!.querySelectorAll<HTMLButtonElement>('button'))
    .find((item) => item.textContent?.includes(label));
  if (!match) throw new Error(`missing button: ${label}`);
  return match;
}

afterEach(async () => {
  if (root) await act(async () => { root!.unmount(); });
  host?.remove();
  root = undefined;
  host = undefined;
  window.sessionStorage.clear();
});

describe('ContinuousVoiceModePanel', () => {
  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  });

  it('requires an explicit user click before enabling continuous voice', async () => {
    const onEnable = vi.fn();
    await renderPanel({ onEnable });

    expect(host!.textContent).toContain('连续语音模式');
    expect(onEnable).not.toHaveBeenCalled();
    await act(async () => { button('开启连续语音模式').click(); });
    expect(onEnable).toHaveBeenCalledTimes(1);
  });

  it('exposes countdown cancellation and fallback actions as text controls', async () => {
    const onCancelCountdown = vi.fn();
    const onDisable = vi.fn();
    await renderPanel({ status: 'end_candidate', countdownSeconds: 3, onCancelCountdown, onDisable });

    expect(host!.textContent).toContain('3 秒后停止录音');
    await act(async () => { button('继续补充').click(); });
    expect(onCancelCountdown).toHaveBeenCalledTimes(1);
    await act(async () => { button('切换标准模式').click(); });
    expect(onDisable).toHaveBeenCalledTimes(1);
  });

  it('allows leaving a pending preflight before the microphone promise resolves', async () => {
    const onDisable = vi.fn();
    await renderPanel({ status: 'preflight', onDisable });

    await act(async () => { button('切换标准模式').click(); });
    expect(onDisable).toHaveBeenCalledTimes(1);
  });
});

describe('InterviewStudio continuous voice integration', () => {
  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    serviceSpies.start.mockResolvedValue({
      attempt_id: 41,
      turn: { turn_no: 1, question: '请介绍一次排障经历。', answer: '', question_kind: 'new_topic', basis_refs: [] },
    });
    serviceSpies.answer.mockResolvedValue({ ok: true });
    serviceSpies.nextQuestion.mockResolvedValue({
      attempt_id: 41,
      turn: { turn_no: 2, question: '你如何验证修复？', answer: '', question_kind: 'follow_up', parent_turn_no: 1, basis_refs: [] },
    });
    serviceSpies.saveVoiceReview.mockResolvedValue({ ok: true });
    serviceSpies.start.mockClear();
    serviceSpies.answer.mockClear();
    serviceSpies.nextQuestion.mockClear();
    serviceSpies.saveVoiceReview.mockClear();
  });

  it('does not call business services during media stages and submits confirmed text once', async () => {
    const onClose = vi.fn();
    await act(async () => {
      root = createRoot(host = document.createElement('div'));
      document.body.appendChild(host);
      root.render(
        <InterviewStudio
          context={{ kind: 'application_event', applicationId: 7, eventId: 8, resumeId: 9, jdVersionId: 10, jdText: '需要排障与回滚能力。', companyName: '示例公司', positionName: '平台工程师' }}
          onClose={onClose}
        />,
      );
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });
    expect(serviceSpies.start).toHaveBeenCalledTimes(1);

    await act(async () => { button('开启连续语音模式').click(); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(serviceSpies.answer).not.toHaveBeenCalled();
    expect(serviceSpies.nextQuestion).not.toHaveBeenCalled();

    await act(async () => { button('结束本轮录音').click(); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(serviceSpies.answer).not.toHaveBeenCalled();

    await act(async () => { button('确认录音文字').click(); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(serviceSpies.answer).toHaveBeenCalledTimes(1);
    expect(serviceSpies.answer).toHaveBeenCalledWith(expect.objectContaining({ answerText: '我先定位日志，再完成回滚。' }));
    expect(serviceSpies.saveVoiceReview).toHaveBeenCalledTimes(1);
    expect(serviceSpies.nextQuestion).toHaveBeenCalledTimes(1);
  });

  it('restores a business result-unknown with the original attempt and turn key', async () => {
    window.sessionStorage.setItem('offerpilot:interview-studio:business-recovery:real:7:8', JSON.stringify({
      attemptKey: 'attempt-original',
      attemptId: 41,
      state: {
        phase: 'result_unknown',
        answerMode: 'text',
        turnNo: 1,
        maxTurns: 5,
        question: 'Describe a debugging incident.',
        answer: 'I located the logs and completed a rollback.',
        turnKey: 'turn-original',
        questionKey: null,
        feedbackKey: null,
        pendingOperation: 'answer',
        resultUnknown: true,
        error: 'Result needs confirmation',
      },
      timeline: [{
        turn_no: 1,
        question: 'Describe a debugging incident.',
        answer: 'I located the logs and completed a rollback.',
        question_kind: 'new_topic',
        basis_refs: [],
        confirmed: false,
      }],
    }));
    const onClose = vi.fn();
    await act(async () => {
      root = createRoot(host = document.createElement('div'));
      document.body.appendChild(host);
      root.render(
        <InterviewStudio
          context={{ kind: 'application_event', applicationId: 7, eventId: 8, resumeId: 9, jdVersionId: 10, jdText: 'Debugging and rollback.', companyName: 'Example', positionName: 'Platform Engineer' }}
          onClose={onClose}
        />,
      );
      await Promise.resolve();
    });
    expect(serviceSpies.start).not.toHaveBeenCalled();
    await act(async () => { button('使用原 key 重试').click(); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(serviceSpies.answer).toHaveBeenCalledWith(expect.objectContaining({
      attemptId: 41,
      turnKey: 'turn-original',
      answerText: 'I located the logs and completed a rollback.',
    }));
    expect(window.sessionStorage.getItem('offerpilot:interview-studio:business-recovery:real:7:8')).toBeNull();
  });
});
