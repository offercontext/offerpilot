import { describe, expect, it } from 'vitest';
import component from './index.tsx?raw';

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
});
