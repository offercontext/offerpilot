import { renderToStaticMarkup } from 'react-dom/server';
import { App as AntApp } from 'antd';
import { describe, expect, it } from 'vitest';
import source from './InterviewV01View.tsx?raw';
import InterviewV01View from './InterviewV01View';

describe('InterviewV01View', () => {
  it('renders the interview index loading surface without mock interview entry points', () => {
    const markup = renderToStaticMarkup(
      <AntApp>
        <InterviewV01View />
      </AntApp>,
    );

    expect(markup).toContain('面试');
    expect(markup).toContain('正在加载面试列表');
    expect(markup).toContain('data-testid="interview-surface"');
    expect(markup).not.toContain('模拟面试');
    expect(markup).not.toContain('新建复盘');
  });

  it('passes the selected event id to the direct preparation entry', () => {
    expect(source).toContain('onOpenPreparation?.(item.application_id, item.event_id)');
    expect(source).toContain('准备面试');
  });
});
