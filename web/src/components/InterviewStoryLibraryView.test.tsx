// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/services/interviewStories', () => ({ listInterviewStories: service.list }));

const { default: InterviewStoryLibraryView } = await import('./InterviewStoryLibraryView');

let root: Root | undefined;
let container: HTMLDivElement | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: () => ({ matches: false, addListener: () => undefined, removeListener: () => undefined }),
  });
  service.list.mockReset();
  service.list.mockResolvedValue([{ id: 8, title: '订单延迟排查', status: 'active', current_version_id: 12, story_revision: 2, version_number: 2, source_states: [] }]);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
});

describe('InterviewStoryLibraryView', () => {
  it('shows a Chinese Story entry and opens a user-initiated draft without writing', async () => {
    const open = vi.fn();
    act(() => root?.render(<InterviewStoryLibraryView onOpenDraft={open} />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(container?.textContent).toContain('面试故事库');
    expect(container?.textContent).toContain('订单延迟排查');
    const create = [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '新建故事');
    act(() => create?.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(open).toHaveBeenCalledWith({ entrypoint: 'ui', reviewNoteId: undefined });
  });
});
