import { describe, expect, it } from 'vitest';
import source from './SettingsView.tsx?raw';

describe('SettingsView localization', () => {
  it('uses Chinese product copy for settings and diagnostics', () => {
    expect(source).toContain('设置');
    expect(source).toContain('AI 运行时');
    expect(source).toContain('运行诊断');
    expect(source).toContain('配置 AI');
    expect(source).toContain('导出备份');
    expect(source).toContain('复制诊断信息');
    expect(source).toContain('重新打开新手引导');
    expect(source).toContain('数据目录');
    expect(source).toContain('日志筛选');
    expect(source).toContain('多供应商');
    expect(source).toContain('Fallback');
    expect(source).not.toContain('>Settings<');
    expect(source).not.toContain('AI runtime');
    expect(source).not.toContain('Runtime diagnostics');
    expect(source).not.toContain('Configure AI');
    expect(source).not.toContain('Details unavailable');
  });
});
