import source from './TopBar.tsx?raw';
import { describe, expect, it } from 'vitest';

describe('top bar actions', () => {
  it('does not expose a redundant right-side chat button', () => {
    expect(source).not.toContain('右侧对话');
    expect(source).not.toContain('onOpenChat');
    expect(source).not.toContain('showContextualPilot');
  });
});
