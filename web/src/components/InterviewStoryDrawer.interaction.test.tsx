// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const storyService = vi.hoisted(() => ({ proposal: vi.fn(), confirm: vi.fn() }));
const noteService = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/services/interviewStories', () => ({
  createInterviewStoryProposal: storyService.proposal,
  confirmInterviewStoryProposal: storyService.confirm,
}));
vi.mock('@/services/notes', () => ({ listNotes: noteService.list }));

const { default: InterviewStoryDrawer, createInterviewStoryDraft } = await import('./InterviewStoryDrawer');

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({ matches: false, addListener: () => undefined, removeListener: () => undefined }),
  });
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => nativeGetComputedStyle(element));
  storyService.proposal.mockReset();
  storyService.confirm.mockReset();
  noteService.list.mockReset();
  noteService.list.mockResolvedValue([{ id: 4, company: '星云数据', position: '后端工程师', questions: '如何排查延迟？', self_reflection: '', difficulty_points: '', mood: '', round: '', date: '', created_at: '' }]);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  vi.restoreAllMocks();
});

describe('InterviewStoryDrawer', () => {
  it('requires selecting an original source and an explicit AI confirmation before proposal generation', async () => {
    const changes: unknown[] = [];
    let current = createInterviewStoryDraft('ui');
    const render = () => root?.render(<InterviewStoryDrawer open draft={current} onDraftChange={(draft) => {
      changes.push(draft);
      if (draft) {
        current = draft;
        render();
      }
    }} onClose={() => {}} />);
    act(render);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.body.textContent).toContain('先选择原始证据');
    expect(storyService.proposal).not.toHaveBeenCalled();

    const select = document.body.querySelector('input[type="checkbox"]') as HTMLInputElement;
    act(() => select?.click());
    const preview = [...document.body.querySelectorAll('button')].find((button) => button.textContent === '查看冻结来源');
    act(() => preview?.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(document.body.textContent).toContain('生成建议前请确认来源');
    expect(storyService.proposal).not.toHaveBeenCalled();
    expect(changes.length).toBeGreaterThan(0);
  });
});
