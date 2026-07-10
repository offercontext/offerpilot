import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Empty,
  Input,
  List,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  FileAddOutlined,
  InboxOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import type { KnowledgeDocument, KnowledgeDocumentInput } from '@/types/knowledge';
import {
  createKnowledgeDocument,
  deleteKnowledgeDocument,
  importKnowledgeDocument,
  listKnowledgeDocuments,
  updateKnowledgeDocument,
} from '@/services/knowledge';
import KnowledgeDocumentEditor from '@/components/KnowledgeDocumentEditor';
import KnowledgeImportModal from '@/components/KnowledgeImportModal';

const { Paragraph, Text } = Typography;

const SOURCE_TYPE_LABELS: Record<string, string> = {
  manual: '手动',
  markdown: 'Markdown',
  paste: '粘贴',
  upload: '导入',
};

const STATUS_LABELS: Record<string, string> = {
  confirmed: '已确认',
  pending: '待确认',
  rejected: '已忽略',
};

export default function KnowledgeLibraryView() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDocument, setEditingDocument] = useState<KnowledgeDocument | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const documentsQuery = useQuery({
    queryKey: ['knowledge-documents', search],
    queryFn: () => listKnowledgeDocuments(search.trim() || undefined),
  });

  const invalidateDocs = () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] });

  const createDocMut = useMutation({
    mutationFn: createKnowledgeDocument,
    onSuccess: () => {
      message.success('文档已创建');
      setEditorOpen(false);
      invalidateDocs();
    },
    onError: () => message.error('创建文档失败'),
  });

  const updateDocMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: KnowledgeDocumentInput }) =>
      updateKnowledgeDocument(id, input),
    onSuccess: () => {
      message.success('文档已更新');
      setEditorOpen(false);
      setEditingDocument(null);
      invalidateDocs();
    },
    onError: () => message.error('更新文档失败'),
  });

  const deleteDocMut = useMutation({
    mutationFn: deleteKnowledgeDocument,
    onSuccess: () => {
      message.success('文档已删除');
      invalidateDocs();
    },
    onError: () => message.error('删除文档失败'),
  });

  const importDocMut = useMutation({
    mutationFn: importKnowledgeDocument,
    onSuccess: () => {
      message.success('文档已导入');
      setImportOpen(false);
      invalidateDocs();
    },
    onError: () => message.error('导入文档失败'),
  });

  function openCreateDocument() {
    setEditingDocument(null);
    setEditorOpen(true);
  }

  function openEditDocument(document: KnowledgeDocument) {
    setEditingDocument(document);
    setEditorOpen(true);
  }

  function saveDocument(input: KnowledgeDocumentInput) {
    if (editingDocument) {
      updateDocMut.mutate({ id: editingDocument.id, input });
      return;
    }
    createDocMut.mutate(input);
  }

  const documents = documentsQuery.data ?? [];
  const loading = documentsQuery.isLoading;

  if (editorOpen) {
    return (
      <div style={{ padding: 24 }}>
        <KnowledgeDocumentEditor
          open={editorOpen}
          document={editingDocument}
          saving={createDocMut.isPending || updateDocMut.isPending}
          onSubmit={saveDocument}
          onClose={() => {
            setEditorOpen(false);
            setEditingDocument(null);
          }}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>
            知识库
          </Typography.Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            个人资料文档与检索地基
          </Paragraph>
        </div>
        <Space>
          <Button icon={<InboxOutlined />} onClick={() => setImportOpen(true)}>
            导入
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateDocument}>
            新建文档
          </Button>
        </Space>
      </div>

      <Input.Search
        allowClear
        placeholder="搜索标题或内容"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        style={{ maxWidth: 420, marginBottom: 16 }}
      />

      {loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : documents.length === 0 ? (
        <Empty description="还没有知识文档" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button type="primary" icon={<FileAddOutlined />} onClick={openCreateDocument}>
            新建第一篇文档
          </Button>
        </Empty>
      ) : (
        <List
          dataSource={documents}
          itemLayout="vertical"
          renderItem={(document) => (
            <List.Item
              key={document.id}
              actions={[
                <Button
                  key="edit"
                  type="text"
                  icon={<EditOutlined />}
                  onClick={() => openEditDocument(document)}
                >
                  编辑
                </Button>,
                <Popconfirm
                  key="delete"
                  title="删除这篇文档？"
                  okText="删除"
                  cancelText="取消"
                  onConfirm={() => deleteDocMut.mutate(document.id)}
                >
                  <Button type="text" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={8} wrap>
                    <Text strong>{document.title}</Text>
                    <Tag>{STATUS_LABELS[document.status] ?? document.status}</Tag>
                    <Tag>{SOURCE_TYPE_LABELS[document.source_type] ?? document.source_type}</Tag>
                    {document.doc_kind && <Tag>{document.doc_kind}</Tag>}
                  </Space>
                }
                description={
                  <Space size={[4, 4]} wrap>
                    {(document.tags ?? []).map((tag) => (
                      <Tag key={tag}>{tag}</Tag>
                    ))}
                  </Space>
                }
              />
              <Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 0 }}>
                {document.content}
              </Paragraph>
            </List.Item>
          )}
        />
      )}

      <KnowledgeImportModal
        open={importOpen}
        uploading={importDocMut.isPending}
        onSubmit={(file) => importDocMut.mutate(file)}
        onClose={() => setImportOpen(false)}
      />
    </div>
  );
}
