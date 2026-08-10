// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  listVersions: vi.fn(),
  getVersion: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
}));
vi.mock('@/services/interviewStories', () => ({
  listInterviewStories: service.list,
  getInterviewStory: service.get,
  listInterviewStoryVersions: service.listVersions,
  getInterviewStoryVersion: service.getVersion,
  archiveInterviewStory: service.archive,
  restoreInterviewStory: service.restore,
}));

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
  service.get.mockReset();
  service.listVersions.mockReset();
  service.getVersion.mockReset();
  service.archive.mockReset();
  service.restore.mockReset();
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

  it('filters archived Stories and reads immutable version history without a write', async () => {
    const open = vi.fn();
    const version = {
      id: 12,
      version_number: 2,
      origin_kind: 'manual' as const,
      confirmed_at: '2026-08-10T00:00:00+00:00',
      source_fingerprint: 'frozen-source',
      content: {
        title: { id: 'title' as const, text: '订单延迟排查' },
        blocks: [{ id: 'situation_001', kind: 'situation' as const, text: '线上延迟', fact_mode: 'evidence_backed' as const }],
        capability_labels: [], applicable_questions: [], fact_gap_codes: [],
      },
      evidence_links: [{
        target_kind: 'title' as const, target_id: 'title', source_kind: 'user_assertion' as const,
        source_stable_id: '1', source_version_or_snapshot: 'assertion:1', source_path: '/statement', excerpt: '这是我的陈述',
      }],
      assertions: [{ id: 1, statement: '这是我的陈述', frozen: true as const }],
      source_states: [{
        source_kind: 'user_assertion' as const, source_stable_id: '1', source_version_or_snapshot: 'assertion:1', state: 'frozen_user_assertion' as const,
      }],
    };
    service.get.mockResolvedValue({ id: 8, title: '订单延迟排查', status: 'active', current_version_id: 12, story_revision: 2, version_number: 2, source_states: [], version });
    service.listVersions.mockResolvedValue([{ id: 12, version_number: 2, origin_kind: 'manual', confirmed_at: version.confirmed_at, source_fingerprint: version.source_fingerprint }]);
    service.getVersion.mockResolvedValue(version);
    act(() => root?.render(<InterviewStoryLibraryView onOpenDraft={open} />));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '查看版本')?.click());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(service.get).toHaveBeenCalledWith(8);
    expect(service.listVersions).toHaveBeenCalledWith(8);
    expect(container?.textContent).toContain('已冻结的用户确认陈述');

    act(() => [...(container?.querySelectorAll('button') ?? [])].find((button) => button.textContent === '已归档')?.click());
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(service.list).toHaveBeenLastCalledWith('archived', '');
    expect(service.archive).not.toHaveBeenCalled();
    expect(service.restore).not.toHaveBeenCalled();
  });
});
