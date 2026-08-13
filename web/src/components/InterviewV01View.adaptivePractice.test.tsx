// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const services = vi.hoisted(() => ({ interviews: vi.fn(), recommendations: vi.fn() }));
vi.mock('@/services/interviews', () => ({ listInterviews: services.interviews }));
vi.mock('@/services/adaptiveInterviewPractice', () => ({
  listAdaptivePracticeRecommendations: services.recommendations,
}));

const { default: InterviewV01View } = await import('./InterviewV01View');
let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  services.interviews.mockReset().mockResolvedValue({ items: [] });
  services.recommendations.mockReset().mockResolvedValue([{
    proposal_id: 4, focus_id: 'focus-1', application_id: 2, application_event_id: 3,
    interview_note_id: 5, company_name: '云栖智能', position_name: '后端工程师',
    drill_kind: 'difficulty_breakdown', title: '拆解卡住的关键一步',
    observation: '影响范围追问时，回答节奏被打断。', reason: '这是复盘里明确记录的卡点。',
    prompt: '写出三步推进方式。', source_path: '/difficulty_points',
    source_excerpt: '被追问影响范围时卡住了。', source_fingerprint: 'fp',
  }]);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => { act(() => root?.unmount()); container?.remove(); });

describe('InterviewV01View adaptive practice entry', () => {
  it('shows one recommendation and only navigates after the user clicks it', async () => {
    const open = vi.fn();
    act(() => root?.render(<InterviewV01View onOpenAdaptivePractice={open} />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container?.textContent).toContain('下一项行动');
    expect(container?.textContent).toContain('拆解卡住的关键一步');
    expect(container?.textContent).toContain('来自已保存复盘');
    expect(container?.textContent).toContain('适合一次短时训练');
    expect(container?.textContent).toContain('不会自动写入故事库');
    expect(open).not.toHaveBeenCalled();
    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent?.includes('开始这项训练'))?.click());
    expect(open).toHaveBeenCalledWith({ proposalId: 4, focusId: 'focus-1' });
    const entry = [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent?.includes('开始这项训练'));
    expect(entry?.className).toContain('ant-btn-lg');
  });

  it('shows a retry state when recommendations cannot be loaded', async () => {
    services.recommendations.mockRejectedValue(new Error('network'));
    act(() => root?.render(<InterviewV01View onOpenAdaptivePractice={() => {}} />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container?.textContent).toContain('复盘训练建议暂时无法加载');
    expect(container?.textContent).toContain('重新加载建议');
  });
});
