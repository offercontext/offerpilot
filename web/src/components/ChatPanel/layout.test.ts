import { describe, expect, it } from 'vitest';
import component from './index.tsx?raw';
import proposalCard from './ProposalCard.tsx?raw';
import thinking from './ThinkingIndicator.tsx?raw';
import threadRail from './ThreadRail.tsx?raw';

async function loadCss(): Promise<string> {
  const fsModule = 'node:fs';
  const { readFileSync } = (await import(fsModule)) as {
    readFileSync: (path: URL, encoding: string) => string;
  };
  return readFileSync(new URL('./ChatPanel.module.css', import.meta.url), 'utf8');
}

describe('ChatPanel docked layout contract', () => {
  it('keeps a new-chat control visible when the docked layout hides the thread rail', () => {
    expect(component).toContain('styles.workspaceDocked');
    expect(component).toContain('<ThreadRail');
    expect(component).toContain('PlusOutlined');
    expect(component).toContain('aria-label="新建对话"');
    expect(component).toContain('docked &&');
  });

  it('lets the docked Pilot expose an action that opens the Pilot tab', () => {
    expect(component).toContain('onExpand');
    expect(component).toContain('ExpandAltOutlined');
    expect(component).toContain('aria-label="打开 Pilot tab"');
  });

  it('supports a normal Pilot tab page variant that reuses the expanded workspace', () => {
    expect(component).toContain("variant?: 'drawer' | 'rail' | 'page'");
    expect(component).toContain("const inlinePage = variant === 'page'");
    expect(component).toContain('if (docked || inlinePage) return workspace');
  });

  it('shows an inline API-key setup notice when the docked context panel is hidden', () => {
    expect(component).toContain('styles.inlineKeyNotice');
    expect(component).toContain('!hasKey &&');
    expect(component).toContain('onOpenSettings');
  });

  it('keeps failed user drafts retryable instead of dropping them', () => {
    expect(component).toContain('lastFailedText');
    expect(component).toContain('retryLastMessage');
    expect(component).toContain('clearLastFailure');
    expect(component).toContain('改成手动整理');
    expect(component).toContain('disabledReason={composerDisabledReason}');
  });

  it('uses concrete waiting states while AI is working', () => {
    expect(thinking).toContain('WAITING_STEPS');
    expect(thinking).toContain('label?: string');
    expect(thinking).toContain('正在理解你的问题');
    expect(thinking).toContain('正在调用工具读取上下文');
    expect(thinking).toContain('正在等待模型返回结果');
    expect(thinking).toContain('正在整理结论和下一步建议');
    expect(component).toContain('loadingLabel');
    expect(component).toContain('<ThinkingIndicator label={loadingLabel}');
  });

  it('lets users stop an in-flight assistant response', () => {
    expect(component).toContain('abortControllerRef');
    expect(component).toContain('stopActiveRequest');
    expect(component).toContain('controller.abort()');
    expect(component).toContain('isAbortError');
    expect(component).toContain('aria-label="停止当前回复"');
    expect(component).toContain('已停止当前回复');
  });

  it('uses Pilot SSE stream services for chat and confirmation flows', () => {
    expect(component).toContain('streamChat');
    expect(component).toContain('streamConfirmAction');
    expect(component).toContain('streamLoadingLabel');
    expect(component).toContain('appendAssistantDelta');
    expect(component).toContain("event.event === 'assistant_delta'");
    expect(component).not.toContain('sendChat,');
    expect(component).not.toContain('confirmAction,');
  });

  it('hides the thinking indicator once assistant text is streaming', () => {
    expect(component).toContain('hasStreamingAssistantContent');
    expect(component).toContain('setHasStreamingAssistantContent(true)');
    expect(component).toContain('loading && !activePending && !hasStreamingAssistantContent');
  });

  it('resynchronizes real conversation state after users abort a stream', () => {
    expect(component).toContain('syncConversationAfterAbort');
    expect(component).toContain('await syncConversationAfterAbort(streamConversationId)');
    expect(component).toContain('await syncConversationAfterAbort(convID)');
    expect(component).toContain('setPending(pendingActionForConversation');
  });

  it('cleans up partial assistant bubbles on stream failure and completed fallback', () => {
    expect(component).toContain('if (streamingAssistantActiveRef.current)');
    expect(component).toContain('await syncConversationAfterAbort(streamConversationId)');
    expect(component).toContain('return [...t.slice(0, -1), { ...last, content: resp.message }];');
  });

  it('notifies owners after Pilot write flows can change application data', () => {
    expect(component).toContain('onDataChanged?: () => void');
    expect(component).toContain('if (autoApprove) onDataChanged?.();');
    expect(component).toContain("resp.write_status === 'success'");
  });

  it('keeps write confirmation cards localized for Chinese users', () => {
    expect(proposalCard).not.toContain('<span>Target</span>');
    expect(proposalCard).not.toContain('<span>Proposed</span>');
    expect(proposalCard).not.toContain('Status ->');
    expect(proposalCard).not.toContain('Evidence is limited');
    expect(proposalCard).toContain('FIELD_LABELS');
    expect(proposalCard).toContain('STATUS_LABELS');
    expect(proposalCard).toContain('EVENT_TYPE_LABELS');
    expect(proposalCard).toContain("duration_minutes: '时长'");
    expect(proposalCard).toContain('参考依据较少');
  });

  it('renders pending write confirmations in a visible dock above the composer', () => {
    expect(component).toContain('styles.pendingDock');
    expect(component).toContain('{activePending && (');
    expect(component.indexOf('styles.pendingDock')).toBeGreaterThan(component.indexOf('</div>'));
    expect(component.indexOf('styles.pendingDock')).toBeLessThan(component.indexOf('<Composer'));
  });

  it('caps oversized confirmation cards and truncates long field values', async () => {
    const css = await loadCss();

    expect(css).toContain('max-height: min(560px, calc(100vh - 140px));');
    expect(css).toContain('overflow-y: auto;');
    expect(css).toContain('-webkit-line-clamp: 4;');
    expect(css).toContain('text-overflow: ellipsis;');
    expect(proposalCard).toContain('className={styles.changeValue}');
    expect(proposalCard).toContain('title={rawAfterText}');
  });

  it('summarizes multi-step write cards and long review fields', () => {
    expect(proposalCard).toContain('action.workflow');
    expect(proposalCard).toContain('第 {action.workflow.current_step} / {action.workflow.total_steps} 步');
    expect(proposalCard).toContain('summarizeLongValue');
    expect(proposalCard).toContain('longDraftFields');
    expect(proposalCard).toContain('action.draft_summary');
    expect(proposalCard).toContain('草稿审阅');
    expect(proposalCard).toContain('长内容已按摘要展示，确认后会完整保存。');
    expect(proposalCard).toContain('action.risk_hint');
    expect(component).toContain('pendingComposerDisabledReason(activePending)');
  });

  it('surfaces pending confirmation recovery and the active conversation context', () => {
    expect(component).toContain('confirmError');
    expect(component).toContain('retryConfirmAction');
    expect(component).toContain('取消本次写入');
    expect(component).toContain('contextBadge');
    expect(component).toContain('当前上下文');
    expect(component).toContain('contextLabel');
  });

  it('lets users manage conversations and remove active context from the Pilot UI', () => {
    expect(threadRail).toContain('PushpinOutlined');
    expect(threadRail).toContain('EditOutlined');
    expect(threadRail).toContain('InboxOutlined');
    expect(threadRail).toContain('onUpdate');
    expect(threadRail).toContain('stopActionPropagation');
    expect(threadRail).toContain('onKeyDown={stopActionPropagation}');
    expect(component).toContain('updateConversation');
    expect(component).toContain('clearActiveContext');
    expect(component).toContain('aria-label="移除当前上下文"');
  });

  it('shows confirmation status and lets users undo the latest AI write', () => {
    expect(component).toContain('confirmPhase');
    expect(component).toContain('保存成功');
    expect(component).toContain('lastUndo');
    expect(component).toContain('undoLastWrite');
    expect(component).toContain('撤销最近一次 AI 写入');
  });

  it('refreshes a new conversation after background title generation', () => {
    expect(component).toContain('titleRefreshTimeoutsRef');
    expect(component).toContain('scheduleTitleRefresh');
    expect(component).toContain('window.setTimeout');
  });

  it('resets the active conversation for every application start request', () => {
    expect(component).toContain('startRequest?.requestKey');
    expect(component).toContain('setConvID(undefined)');
    expect(component).toContain('setTurns([])');
    expect(component).toContain('draftContext');
  });

  it('does not auto-resume an older pending thread after an application start request', () => {
    expect(component).toContain('skipPendingResumeRef');
    expect(component).toContain('skipPendingResumeRef.current = true');
    expect(component).toContain('if (skipPendingResumeRef.current)');
  });

  it('clears unsent composer text when an application start request opens a new draft', () => {
    expect(component).toContain('composerResetKey');
    expect(component).toContain('resetKey={composerResetKey}');
  });

  it('uses structured write status instead of treating every message response as success', () => {
    expect(component).toContain('resp.write_status === \'success\'');
    expect(component).toContain('resp.write_status === \'failed\'');
    expect(component).toContain('resp.write_error');
  });
});
