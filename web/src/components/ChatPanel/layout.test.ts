import { describe, expect, it } from 'vitest';
import component from './index.tsx?raw';
import proposalCard from './ProposalCard.tsx?raw';
import thinking from './ThinkingIndicator.tsx?raw';

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

  it('lets the docked Pilot expand into the full assistant drawer', () => {
    expect(component).toContain('onExpand');
    expect(component).toContain('ExpandAltOutlined');
    expect(component).toContain('aria-label="展开完整助手"');
  });

  it('shows an inline API-key setup notice when the docked context panel is hidden', () => {
    expect(component).toContain('styles.inlineKeyNotice');
    expect(component).toContain('!hasKey &&');
    expect(component).toContain('onOpenSettings');
  });

  it('keeps failed user drafts retryable instead of dropping them', () => {
    expect(component).toContain('lastFailedText');
    expect(component).toContain('retryLastMessage');
    expect(component).toContain('disabledReason={composerDisabledReason}');
  });

  it('uses concrete waiting states while AI is working', () => {
    expect(thinking).toContain('WAITING_STEPS');
    expect(thinking).toContain('正在理解你的问题');
    expect(thinking).toContain('正在调用工具读取上下文');
    expect(thinking).toContain('正在等待模型返回结果');
    expect(thinking).toContain('正在整理结论和下一步建议');
  });

  it('lets users stop an in-flight assistant response', () => {
    expect(component).toContain('abortControllerRef');
    expect(component).toContain('stopActiveRequest');
    expect(component).toContain('controller.abort()');
    expect(component).toContain('isAbortError');
    expect(component).toContain('aria-label="停止当前回复"');
    expect(component).toContain('已停止当前回复');
  });

  it('notifies owners after Pilot write flows can change application data', () => {
    expect(component).toContain('onDataChanged?: () => void');
    expect(component).toContain('if (autoApprove) onDataChanged?.();');
    expect(component).toContain('if (approved) onDataChanged?.();');
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
    expect(proposalCard).toContain('action.risk_hint');
    expect(component).toContain('pendingComposerDisabledReason(activePending)');
  });
});
