import { describe, expect, it } from 'vitest';
import source from './InterviewKnowledgeCaptureDrawer.tsx?raw';

describe('InterviewKnowledgeCaptureDrawer', () => {
  it('keeps raw fragments separate from editable preview and requires confirmation', () => {
    expect(source).toContain('直接保存选中原文');
    expect(source).toContain('生成笔记预览');
    expect(source).toContain('用户选中的原始片段');
    expect(source).toContain('AI 笔记预览');
    expect(source).toContain('证据引用');
    expect(source).toContain('window.confirm');
    expect(source).toContain('confirmInterviewKnowledgeCapture');
    expect(source).not.toContain('createQuestion');
    expect(source).not.toContain('createMemory');
  });

  it('handles safe empty preview and unknown delete result without leaking raw errors', () => {
    expect(source).toContain('暂无可验证的笔记预览');
    expect(source).toContain('操作结果未知，请重新打开复盘确认状态');
    expect(source).toContain('capture_attempt_confirmed');
    expect(source).not.toContain('error.message');
    expect(source).not.toContain('error.response?.data?.error');
  });
});
