import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import InterviewV01View from './InterviewV01View';

describe('InterviewV01View', () => {
  it('renders the v0.1 empty interview surface without formal mock or notes entry points', () => {
    const markup = renderToStaticMarkup(<InterviewV01View />);

    expect(markup).toContain('面试');
    expect(markup).toContain('暂无面试记录');
    expect(markup).toContain('保存');
    expect(markup).not.toContain('模拟面试');
    expect(markup).not.toContain('新建复盘');
  });
});
