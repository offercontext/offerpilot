import { renderToStaticMarkup } from 'react-dom/server';
import { App as AntApp } from 'antd';
import { describe, expect, it } from 'vitest';
import InterviewV01View from './InterviewV01View';

describe('InterviewV01View', () => {
  it('renders the interview index loading surface without mock interview entry points', () => {
    const markup = renderToStaticMarkup(
      <AntApp>
        <InterviewV01View />
      </AntApp>
    );

    expect(markup).toContain('面试');
    expect(markup).toContain('正在加载面试列表');
    expect(markup).not.toContain('模拟面试');
    expect(markup).not.toContain('新建复盘');
  });
});
