// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import type { Resume } from '@/types/resume';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  updateResume: vi.fn(),
  aiService: vi.fn(),
}));

vi.mock('@/services/resumes', () => ({
  updateResume: state.updateResume,
}));

vi.mock('@/services/ai', () => ({
  analyzeJD: state.aiService,
  listJDAnalyses: state.aiService,
}));

import ResumeEditorDrawer from './ResumeEditorDrawer';

let root: Root | undefined;
let container: HTMLDivElement | undefined;
let fetchSpy: { mockRestore: () => void };
let xhrOpenSpy: ReturnType<typeof vi.spyOn>;
let pushStateSpy: ReturnType<typeof vi.spyOn>;
let replaceStateSpy: ReturnType<typeof vi.spyOn>;
let onClose: ReturnType<typeof vi.fn>;
let onSaved: ReturnType<typeof vi.fn>;

const resume: Resume = {
  id: 1,
  name: '测试简历',
  file_path: '',
  parsed_data: '',
  parse_status: 'text-ready',
  title: '测试简历',
  is_master: true,
  parent_resume_id: null,
  source: 'manual',
  source_file_path: '',
  content_json: {
    contact: { name: '林晓' },
    education: [],
    experience: [{ highlights: ['负责订单服务'] }],
    projects: [],
    skills: ['TypeScript'],
    career_intent: { target_roles: ['前端工程师'] },
  },
  deleted_at: null,
  created_at: '2026-08-06T00:00:00Z',
  completion_percent: 60,
  missing_sections: ['education'],
  is_complete: false,
};

function renderEditor() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  onClose = vi.fn();
  onSaved = vi.fn();

  act(() => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <AntApp>
          <ResumeEditorDrawer resume={resume} open onClose={onClose} onSaved={onSaved} />
        </AntApp>
      </QueryClientProvider>,
    );
  });
}

function findButton(label: string): HTMLButtonElement {
  const button = Array.from(container?.querySelectorAll('button') ?? [])
    .find((item) => item.textContent?.includes(label));
  if (!(button instanceof HTMLButtonElement)) throw new Error(`button not found: ${label}`);
  return button;
}

async function click(element: Element) {
  await act(async () => {
    (element as HTMLElement).click();
  });
}

beforeEach(() => {
  state.updateResume.mockReset();
  state.aiService.mockReset();
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  fetchSpy = vi.spyOn(globalThis, 'fetch');
  xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, 'open');
  pushStateSpy = vi.spyOn(window.history, 'pushState');
  replaceStateSpy = vi.spyOn(window.history, 'replaceState');
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  fetchSpy.mockRestore();
  xhrOpenSpy.mockRestore();
  pushStateSpy.mockRestore();
  replaceStateSpy.mockRestore();
  root = undefined;
  container = undefined;
});

describe('ResumeEditorDrawer mounted audit flow', () => {
  it('opens, expands, collapses, and closes the audit without write, AI, HTTP, or navigation calls', async () => {
    renderEditor();

    const openButton = findButton('简历事实体检');
    expect(openButton.getAttribute('aria-expanded')).toBe('false');
    expect(container?.textContent).not.toContain('只检查当前简历中可观察的信息');

    await click(openButton);
    expect(openButton.getAttribute('aria-expanded')).toBe('true');
    expect(container?.textContent).toContain('只检查当前简历中可观察的信息');
    expect(container?.textContent).toContain('无法判断');

    const details = container?.querySelector('details') as HTMLDetailsElement;
    const summary = details?.querySelector('summary') as HTMLElement;
    expect(details?.open).toBe(false);
    await click(summary);
    expect(details?.open).toBe(true);
    await click(summary);
    expect(details?.open).toBe(false);

    await click(openButton);
    expect(openButton.getAttribute('aria-expanded')).toBe('false');
    expect(container?.textContent).not.toContain('只检查当前简历中可观察的信息');
    expect(state.updateResume).not.toHaveBeenCalled();
    expect(state.aiService).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(xhrOpenSpy).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(pushStateSpy).not.toHaveBeenCalled();
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });
});
