import { describe, expect, it } from 'vitest';
import source from './AISettingsDrawer.tsx?raw';

describe('AISettingsDrawer localization', () => {
  it('uses Chinese labels for the AI configuration form', () => {
    expect(source).toContain('AI 设置');
    expect(source).toContain('Provider 列表');
    expect(source).toContain('新增供应商');
    expect(source).toContain('编辑供应商');
    expect(source).toContain('删除供应商');
    expect(source).toContain('设为默认');
    expect(source).toContain('Fallback 供应商');
    expect(source).toContain('测试连接');
    expect(source).toContain('provider_id: values.id');
    expect(source).toContain('模型供应商');
    expect(source).toContain('接口地址');
    expect(source).toContain('保存');
    expect(source).toContain('写操作自动确认');
    expect(source).not.toContain('label="Provider"');
    expect(source).not.toContain('label="Base URL"');
    expect(source).not.toContain('OpenAI-compatible API base');
  });

  it('exposes multi-provider management, fallback order, and connectivity testing', () => {
    expect(source).toContain('fallbackProviderIds');
    expect(source).toContain('fallback_provider_ids');
    expect(source).toContain('mode="multiple"');
    expect(source).toContain('testProviderConnection');
    expect(source).toContain('测试连接');
    expect(source).toContain('设为默认');
    expect(source).toContain('Fallback 供应商');
  });
});
