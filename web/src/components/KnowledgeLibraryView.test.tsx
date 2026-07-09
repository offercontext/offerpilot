import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp } from 'antd';
import { describe, expect, it } from 'vitest';
import type { KnowledgeDocument } from '@/types/knowledge';
import KnowledgeLibraryView from './KnowledgeLibraryView';
import source from './KnowledgeLibraryView.tsx?raw';

function renderWithDocuments(documents: KnowledgeDocument[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  queryClient.setQueryData(['knowledge-documents', ''], documents);

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <AntApp>
        <KnowledgeLibraryView />
      </AntApp>
    </QueryClientProvider>,
  );
}

function document(patch: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    id: 7,
    title: '系统设计面试知识',
    content: '缓存、限流、消息队列和一致性设计要点。',
    tags: ['系统设计', '后端'],
    doc_kind: 'wiki',
    status: 'confirmed',
    source_type: 'manual',
    source_name: '',
    source_refs: '',
    summary_type: '',
    generation_meta: '',
    superseded_by: null,
    confirmed_at: null,
    created_at: '2026-07-09T10:00:00Z',
    updated_at: '2026-07-09T10:00:00Z',
    ...patch,
  };
}

describe('KnowledgeLibraryView', () => {
  it('renders the empty knowledge-library path with create and import entry points', () => {
    const markup = renderWithDocuments([]);

    expect(markup).toContain('知识库');
    expect(markup).toContain('个人资料文档与检索地基');
    expect(markup).toContain('搜索标题或内容');
    expect(markup).toContain('导入');
    expect(markup).toContain('新建文档');
    expect(markup).toContain('还没有知识文档');
    expect(markup).toContain('新建第一篇文档');
  });

  it('renders indexed documents with source, status, tags, and edit/delete controls', () => {
    const markup = renderWithDocuments([document()]);

    expect(markup).toContain('系统设计面试知识');
    expect(markup).toContain('缓存、限流、消息队列和一致性设计要点。');
    expect(markup).toContain('已确认');
    expect(markup).toContain('手动');
    expect(markup).toContain('系统设计');
    expect(markup).toContain('后端');
    expect(markup).toContain('编辑');
    expect(markup).toContain('删除');
  });

  it('keeps the page wired to real knowledge CRUD, import, and search APIs', () => {
    expect(source).toContain('listKnowledgeDocuments(search.trim() || undefined)');
    expect(source).toContain('createKnowledgeDocument');
    expect(source).toContain('updateKnowledgeDocument');
    expect(source).toContain('deleteKnowledgeDocument');
    expect(source).toContain('importKnowledgeDocument');
    expect(source).toContain("invalidateQueries({ queryKey: ['knowledge-documents'] })");
  });
});
