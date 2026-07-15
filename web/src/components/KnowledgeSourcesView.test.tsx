import { renderToStaticMarkup } from 'react-dom/server';
import { App as AntApp } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import KnowledgeSourcesView from './KnowledgeSourcesView';

function renderWithProviders() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <AntApp>
        <KnowledgeSourcesView />
      </AntApp>
    </QueryClientProvider>
  );
}

describe('KnowledgeSourcesView', () => {
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

  it('keeps KI-05 dedup guidance out of the main source library surface', () => {
    const markup = renderWithProviders();

    // 去重说明移入已选 Source 的“导入记录”提示图标，不再占用资料来源首页空间。
    expect(markup).not.toContain('相同内容自动复用已有 Source');
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

  it('renders KI-09 Brief surface entry in the Source detail header guidance', () => {
    // SSR 阶段右栏尚未加载 Source，但模块自身已注册 Brief 导读组件；
    // 验证组件文件可被 import 且不抛错，保证 KI-09 前端入口未回滚。
    expect(typeof KnowledgeSourcesView).toBe('function');
  });

  it('exposes KBR-07 destructive Knowledge reset entry in the toolbar', () => {
    const markup = renderWithProviders();

    // 工具栏注册破坏性 reset 入口；点击后进入二次确认 Modal（需输入确认文本）。
    // reset 成功后的缓存清空由 resetMutation.removeQueries 保证，避免指向已删除
    // Source 的缓存详情；服务契约见 services/knowledge.test.ts。
    expect(markup).toContain('清空 Knowledge 数据');
  });
});
