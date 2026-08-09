// @vitest-environment jsdom
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App as AntApp } from 'antd';
import ProposalCard from './ProposalCard';
import type { PendingAction } from '@/types/chat';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
if (!HTMLElement.prototype.scrollIntoView) HTMLElement.prototype.scrollIntoView = vi.fn();

const chatState = vi.hoisted(() => ({
  streamChat: vi.fn(),
}));

vi.mock('@/services/chat', () => ({
  streamChat: chatState.streamChat,
  streamConfirmAction: vi.fn(),
  getSettings: vi.fn().mockResolvedValue({ chat_auto_approve_writes: false }),
  SETTINGS_QUERY_KEY: ['settings'],
  updateAutoApprove: vi.fn(),
  listConversations: vi.fn().mockResolvedValue([]),
  getConversation: vi.fn().mockResolvedValue([]),
  deleteConversation: vi.fn(),
  updateConversation: vi.fn(),
  undoLastWrite: vi.fn(),
}));
vi.mock('@/services/offers', () => ({ getOffer: vi.fn() }));
vi.mock('@/services/onboarding', () => ({ ONBOARDING_QUERY_KEY: ['onboarding'] }));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: [], isLoading: false }),
}));
vi.mock('@/features/pilot/PilotAttachmentContext', () => ({
  usePilotAttachments: () => ({
    activeKey: undefined,
    attachments: [],
    notice: null,
    addAttachment: vi.fn(),
    removeAttachment: vi.fn(),
    setActiveConversationKey: vi.fn(),
    clearAttachmentsByKey: vi.fn(),
    beginNewAttachmentDraft: vi.fn(() => 'draft'),
    ensureNewAttachmentDraft: vi.fn(() => 'draft'),
  }),
}));
vi.mock('./ThreadRail', () => ({ default: () => null }));
vi.mock('./MessageBubble', () => ({ default: () => null }));
vi.mock('./ThinkingIndicator', () => ({ default: () => null }));
vi.mock('./Composer', () => ({ default: () => null }));
vi.mock('./ContextAttachmentRail', () => ({ default: () => null }));
vi.mock('./NativePilotAttachmentDropSurface', () => ({ default: (props: { children?: ReactNode }) => <>{props.children}</> }));
vi.mock('./ContextPanel', () => ({ default: () => null }));
vi.mock('@/components/KanbanBoard/PilotContextDropTarget', () => ({ default: (props: { children?: ReactNode }) => <>{props.children}</> }));

const { default: ChatPanel } = await import('./index');

let root: Root | undefined;
let container: HTMLDivElement | undefined;

afterEach(() => {
  chatState.streamChat.mockReset();
  act(() => root?.unmount());
  container?.remove();
});

function renderProposal(action: PendingAction) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root?.render(
    <AntApp>
      <ProposalCard action={action} loading={false} evidence={[]} onConfirm={vi.fn()} onCancel={vi.fn()} />
    </AntApp>,
  ));
  return container;
}

const jdAction: PendingAction = {
  tool_name: 'save_application_jd_version',
  human: '请确认将这份岗位资料保存到当前投递。',
  confirmation_token: 'token',
  args: {
    application_id: 7,
    jd_text: '负责服务端系统设计与开发，参与稳定性建设。',
    source_url: 'https://example.invalid/job/7',
    expected_current_version_id: 3,
    idempotency_key: 'abcdefghijklmnop',
  },
  target: {
    id: 'application-7',
    kind: 'application',
    title: '示例公司',
    meta: '后端工程师',
    source: 'pending_action',
  },
  application_jd: {
    current_version_number: 3,
    proposed_version_number: 4,
  },
  editable_fields: [
    { field: 'jd_text', type: 'long_text' },
    { field: 'source_url', type: 'string', clearable: true, clear_value: null },
  ],
};

describe('deterministic Pilot JD confirmation card', () => {
  it('starts the Chat stream with the application context and public pilot action', async () => {
    chatState.streamChat.mockResolvedValue({
      type: 'message',
      conversation_id: 101,
      message: '已准备确认卡',
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root?.render(
      <AntApp>
        <ChatPanel
          open
          variant="page"
          onClose={vi.fn()}
          startRequest={{
            requestKey: 1,
            context_type: 'application',
            context_ref: '7',
            context_label: '示例公司 · 后端工程师',
            mode: 'general',
            initialMessage: '保存岗位资料',
            pilot_action: { type: 'application_jd_save' },
          }}
        />
      </AntApp>,
    ));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(chatState.streamChat).toHaveBeenCalledWith(
      '保存岗位资料',
      undefined,
      expect.objectContaining({
        context_type: 'application',
        context_ref: '7',
        pilot_action: { type: 'application_jd_save' },
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('does not replay a consumed quick entry after the panel remounts', async () => {
    chatState.streamChat.mockResolvedValue({
      type: 'message',
      conversation_id: 102,
      message: '已准备确认卡',
    });
    const consumed = new Set<number>();
    const claim = (requestKey: number) => {
      if (consumed.has(requestKey)) return false;
      consumed.add(requestKey);
      return true;
    };
    const startRequest = {
      requestKey: 2,
      context_type: 'application' as const,
      context_ref: '7',
      context_label: '示例公司 · 后端工程师',
      mode: 'general' as const,
      initialMessage: '保存岗位资料',
      pilot_action: { type: 'application_jd_save' as const },
    };
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root?.render(
      <AntApp>
        <ChatPanel open variant="page" onClose={vi.fn()} startRequest={startRequest} onStartRequestConsumed={claim} />
      </AntApp>,
    ));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    act(() => root?.unmount());
    root = createRoot(container);
    act(() => root?.render(
      <AntApp>
        <ChatPanel open variant="page" onClose={vi.fn()} startRequest={startRequest} onStartRequestConsumed={claim} />
      </AntApp>,
    ));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(chatState.streamChat).toHaveBeenCalledTimes(1);
  });

  it('mounts the application facts and keeps source URL text-only', () => {
    const view = renderProposal(jdAction);
    expect(view.textContent).toContain('示例公司');
    expect(view.textContent).toContain('后端工程师');
    expect(view.textContent).toContain('当前版本');
    expect(view.textContent).toContain('拟创建版本');
    expect(view.textContent).toContain('v4');
    expect(view.textContent).toContain('JD 预览');
    expect(view.textContent).toContain('字符数');
    expect(view.textContent).toContain('Pilot');
    expect(view.textContent).toContain('不会访问链接');
    expect(view.querySelector('a')).toBeNull();
  });

  it('only exposes JD text and source URL as editable controls', () => {
    const view = renderProposal(jdAction);
    const disclosure = view.querySelector<HTMLButtonElement>('[aria-expanded]');
    act(() => disclosure?.click());
    expect(view.querySelector('textarea')).not.toBeNull();
    expect(view.querySelector('input')).not.toBeNull();
    expect(view.textContent).not.toContain('application_id');
    expect(view.textContent).not.toContain('idempotency_key');
  });
});
