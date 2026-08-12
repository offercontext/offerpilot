// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  recommendations: vi.fn(),
  plans: vi.fn(),
  start: vi.fn(),
  complete: vi.fn(),
}));

vi.mock('@/services/adaptiveInterviewPractice', () => ({
  listAdaptivePracticeRecommendations: service.recommendations,
  listAdaptivePracticePlans: service.plans,
  startAdaptivePractice: service.start,
  completeAdaptivePractice: service.complete,
  AdaptivePracticeError: class extends Error {
    code?: string;
    constructor(code?: string) { super(code ?? 'unknown'); this.code = code; }
  },
}));

const { default: AdaptiveInterviewPracticeWorkspace } = await import('./AdaptiveInterviewPracticeWorkspace');

let root: Root | undefined;
let container: HTMLDivElement | undefined;

const recommendation = {
  proposal_id: 4,
  focus_id: 'focus-1',
  application_id: 2,
  application_event_id: 3,
  interview_note_id: 5,
  company_name: '云栖智能',
  position_name: '后端工程师',
  drill_kind: 'difficulty_breakdown' as const,
  title: '拆解卡住的关键一步',
  observation: '影响范围追问时，回答节奏被打断。',
  reason: '这个问题在复盘中被明确记录为卡点。',
  prompt: '写出当时卡住的具体节点，并用三步说明下一次如何推进。',
  source_path: '/difficulty_points',
  source_excerpt: '被追问影响范围时卡住了。',
  source_fingerprint: 'source-fingerprint',
};

const plan = {
  id: 8,
  ...recommendation,
  status: 'in_progress' as const,
  revision: 1,
  response_text: '',
  reflection_text: '',
  self_assessment: '',
  source_status: 'current' as const,
  created_at: '2026-08-12T10:00:00Z',
  completed_at: null,
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({ matches: false, addListener: () => undefined, removeListener: () => undefined }),
  });
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element));
  service.recommendations.mockReset().mockResolvedValue([recommendation]);
  service.plans.mockReset().mockResolvedValue([]);
  service.start.mockReset().mockResolvedValue(plan);
  service.complete.mockReset().mockResolvedValue({ ...plan, status: 'completed', revision: 2, self_assessment: 'clearer' });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  sessionStorage.clear();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  vi.restoreAllMocks();
});

describe('AdaptiveInterviewPracticeWorkspace', () => {
  it('requires explicit confirmation before starting and shows frozen evidence', async () => {
    act(() => root?.render(<AdaptiveInterviewPracticeWorkspace />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(container?.textContent).toContain('拆解卡住的关键一步');
    expect(container?.textContent).toContain('被追问影响范围时卡住了。');
    expect(service.start).not.toHaveBeenCalled();
    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent?.includes('查看并开始'))?.click());
    expect(document.body.textContent).toContain('开始前确认');
    expect(service.start).not.toHaveBeenCalled();
    await act(async () => {
      [...document.body.querySelectorAll('button')].find((button) => button.textContent === '确认开始')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(service.start).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain('练习进行中');
  });

  it('completes a plan with a semantic self assessment and keeps a readonly history', async () => {
    service.recommendations.mockResolvedValue([]);
    service.plans.mockResolvedValue([plan]);
    act(() => root?.render(<AdaptiveInterviewPracticeWorkspace />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    const response = container?.querySelector('textarea[aria-label="练习回答"]') as HTMLTextAreaElement;
    const reflection = container?.querySelector('textarea[aria-label="练习复盘"]') as HTMLTextAreaElement;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(response, '先说明影响范围，再讲定位和恢复结果。');
      response.dispatchEvent(new Event('input', { bubbles: true }));
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(reflection, '下一次先给结论。');
      reflection.dispatchEvent(new Event('input', { bubbles: true }));
    });
    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent?.includes('更清楚了'))?.click());
    await act(async () => {
      [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '完成本次练习')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(service.complete).toHaveBeenCalledWith(8, expect.objectContaining({
      response_text: '先说明影响范围，再讲定位和恢复结果。',
      reflection_text: '下一次先给结论。',
      self_assessment: 'clearer',
    }));
  });

  it('retains an unknown completion key and frozen input across remount', async () => {
    service.recommendations.mockResolvedValue([]);
    service.plans.mockResolvedValue([plan]);
    service.complete.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ ...plan, status: 'completed', revision: 2, self_assessment: 'clearer' });
    act(() => root?.render(<AdaptiveInterviewPracticeWorkspace />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const response = container?.querySelector('textarea[aria-label="练习回答"]') as HTMLTextAreaElement;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(response, '保留的原回答');
      response.dispatchEvent(new Event('input', { bubbles: true }));
    });
    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent?.includes('更清楚了'))?.click());
    await act(async () => {
      [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '完成本次练习')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container?.textContent).toContain('使用原操作重试');
    const firstKey = service.complete.mock.calls[0][1].idempotency_key;

    act(() => root?.unmount());
    root = createRoot(container!);
    act(() => root?.render(<AdaptiveInterviewPracticeWorkspace />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect((container?.querySelector('textarea[aria-label="练习回答"]') as HTMLTextAreaElement).value).toBe('保留的原回答');
    await act(async () => {
      [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '使用原操作重试')?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(service.complete.mock.calls[1][1].idempotency_key).toBe(firstKey);
  });
});
