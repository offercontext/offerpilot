import source from './MockInterviewDrawer.tsx?raw';
import { describe, expect, it } from 'vitest';

describe('MockInterviewDrawer safety display contract', () => {
  it('maps failures to fixed Chinese messages without rendering raw errors', () => {
    expect(source).toContain('function safeError(error: unknown)');
    expect(source).toContain('AI 输出未通过验证，请重新开始本次模拟面试。');
    expect(source).toContain('AI 服务暂不可用，结果待确认，请使用原尝试重试。');
    expect(source).not.toContain('error.message');
    expect(source).not.toContain('error.response.data.error');
    expect(source).not.toContain('response.data.error');
  });
});
