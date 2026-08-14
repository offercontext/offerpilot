// @vitest-environment jsdom
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import InterviewReadinessCenter from './InterviewReadinessCenter';

describe('InterviewReadinessCenter', () => {
  it('explains both modes and keeps entry disabled until required sources are ready', () => {
    const markup = renderToStaticMarkup(
      <InterviewReadinessCenter applications={[]} events={[]} resumes={[]} />,
    );

    expect(markup).toContain('围绕真实投递练习');
    expect(markup).toContain('快速练习');
    expect(markup).toContain('开始前检查');
    expect(markup).toContain('当前 JD（只读）');
    expect(markup).toContain('进入模拟面试');
    expect(markup).toContain('disabled=""');
  });
});
