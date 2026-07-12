import { renderToStaticMarkup } from 'react-dom/server';
import { App as AntApp } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import KnowledgeWikiView from './KnowledgeWikiView';

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <AntApp>
        <KnowledgeWikiView />
      </AntApp>
    </QueryClientProvider>
  );
}

describe('KnowledgeWikiView', () => {
  it('renders Source library surface with upload, paste entries and search box', () => {
    const markup = renderWithProviders();

    expect(markup).toContain('资料来源');
    expect(markup).toContain('上传 Markdown / Text');
    expect(markup).toContain('粘贴正文');
    expect(markup).toContain('Evidence');
    // SSR 阶段 React Query 处于 loading 状态；右栏空状态提供引导文案。
    expect(markup).toContain('选择左侧的 Source 查看详情');
    expect(markup).not.toContain('Wiki');
    expect(markup).not.toContain('Page');
  });

  it('does not expose legacy Page/Review/Index/Lint/Config entries', () => {
    const markup = renderWithProviders();

    expect(markup).not.toContain('自动 Wiki');
    expect(markup).not.toContain('Wikilink');
    expect(markup).not.toContain('Protected Page');
    expect(markup).not.toContain('Mutation Review');
  });
});
