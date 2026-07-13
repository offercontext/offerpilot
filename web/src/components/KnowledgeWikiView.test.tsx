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
  it('renders Source library surface with upload, bundle, paste entries and search box', () => {
    const markup = renderWithProviders();

    expect(markup).toContain('资料来源');
    expect(markup).toContain('上传 Markdown / Text');
    expect(markup).toContain('上传图文 Bundle');
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

  it('exposes KI-05 dedup helper text without legacy wiki surface', () => {
    const markup = renderWithProviders();

    // KI-05 dedup 提示文案出现在粘贴/上传入口附近,引导用户去已有 Source。
    expect(markup).toContain('进入已有 Source');
    expect(markup).toContain('Origin');
    expect(markup).not.toContain('自动创建 Page');
  });

  it('renders KI-06 archive filter switch without legacy wiki surface', () => {
    const markup = renderWithProviders();

    expect(markup).toContain('显示归档资料');
    // 危险区永久删除入口在 Source 详情中,SSR 时不会出现(需要选中 Source),
    // 但服务契约由 services/knowledge.test.ts 验证。
  });

  it('exposes KI-08 evidence search entry with CJK-friendly placeholder', () => {
    const markup = renderWithProviders();

    expect(markup).toContain('搜索 Evidence');
    expect(markup).toContain('中文/英文关键词');
  });
});
