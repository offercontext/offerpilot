import { describe, expect, it } from 'vitest';
import component from './index.tsx?raw';
import thinking from './ThinkingIndicator.tsx?raw';

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
    expect(thinking).toContain('正在整理结论和下一步建议');
  });

  it('notifies owners after Pilot write flows can change application data', () => {
    expect(component).toContain('onDataChanged?: () => void');
    expect(component).toContain('if (autoApprove) onDataChanged?.();');
    expect(component).toContain('if (approved) onDataChanged?.();');
  });
});
