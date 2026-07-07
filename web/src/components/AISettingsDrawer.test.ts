import { describe, expect, it } from 'vitest';
import source from './AISettingsDrawer.tsx?raw';

describe('AISettingsDrawer localization', () => {
  it('uses Chinese labels for the AI configuration form', () => {
    expect(source).toContain('AI 设置');
    expect(source).toContain('模型供应商');
    expect(source).toContain('接口地址');
    expect(source).toContain('保存');
    expect(source).toContain('写操作自动确认');
    expect(source).not.toContain('label="Provider"');
    expect(source).not.toContain('label="Base URL"');
    expect(source).not.toContain('OpenAI-compatible API base');
  });
});
