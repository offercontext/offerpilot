import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Empty,
  Form,
  Grid,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Tooltip,
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
import type {
  KnowledgeBase,
  KnowledgeBaseInput,
  KnowledgeDocument,
  KnowledgeDocumentInput,
} from '@/types/knowledge';
import {
  createKnowledgeBase,
  createKnowledgeDocument,
  deleteKnowledgeBase,
  deleteKnowledgeDocument,
  importKnowledgeDocument,
  listKnowledgeBases,
  listKnowledgeDocuments,
  updateKnowledgeBase,
  updateKnowledgeDocument,
} from '@/services/knowledge';
import KnowledgeDocumentEditor from '@/components/KnowledgeDocumentEditor';
import KnowledgeImportModal from '@/components/KnowledgeImportModal';

const { Paragraph, Text } = Typography;

type BaseFormValues = {
  name: string;
  description?: string;
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  manual: '手动',
  upload: '导入',
};

export default function KnowledgeBaseView() {
  const queryClient = useQueryClient();
  const screens = Grid.useBreakpoint();
  const [selectedBaseId, setSelectedBaseId] = useState<number | undefined>();
  const [search, setSearch] = useState('');
  const [baseModalOpen, setBaseModalOpen] = useState(false);
  const [editingBase, setEditingBase] = useState<KnowledgeBase | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingDocument, setEditingDocument] = useState<KnowledgeDocument | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [baseForm] = Form.useForm<BaseFormValues>();

  const basesQuery = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: listKnowledgeBases,
  });

  const documentsQuery = useQuery({
    queryKey: ['knowledge-documents', selectedBaseId, search],
    queryFn: () => listKnowledgeDocuments(selectedBaseId, search.trim() || undefined),
    enabled: !!selectedBaseId,
  });

  const invalidateBases = () => queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
  const invalidateDocs = () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] });

  const bases = basesQuery.data ?? [];
  const documents = documentsQuery.data ?? [];
  const isNarrow = !screens.md;
  const selectedBase = useMemo(
    () => bases.find((base) => base.id === selectedBaseId),
    [bases, selectedBaseId],
  );

  useEffect(() => {
    if (bases.length === 0) {
      setSelectedBaseId(undefined);
      return;
    }

    if (!selectedBaseId || !bases.some((base) => base.id === selectedBaseId)) {
      setSelectedBaseId(bases[0].id);
    }
  }, [bases, selectedBaseId]);

  const createBaseMut = useMutation({
    mutationFn: createKnowledgeBase,
    onSuccess: (base) => {
      message.success('知识库已创建');
      setBaseModalOpen(false);
      setEditingBase(null);
      baseForm.resetFields();
      setSelectedBaseId(base.id);
      invalidateBases();
    },
    onError: () => message.error('创建知识库失败'),
  });

  const updateBaseMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: KnowledgeBaseInput }) =>
      updateKnowledgeBase(id, input),
    onSuccess: () => {
      message.success('知识库已更新');
      setBaseModalOpen(false);
      setEditingBase(null);
      baseForm.resetFields();
      invalidateBases();
    },
    onError: () => message.error('更新知识库失败'),
  });

  const deleteBaseMut = useMutation({
    mutationFn: deleteKnowledgeBase,
    onSuccess: (_, id) => {
      const cachedBases = queryClient.getQueryData<KnowledgeBase[]>(['knowledge-bases']) ?? bases;
      const nextBases = cachedBases.filter((base) => base.id !== id);

      queryClient.setQueryData<KnowledgeBase[]>(['knowledge-bases'], nextBases);
      message.success('知识库已删除');
      if (selectedBaseId === id) {
        setSelectedBaseId(nextBases[0]?.id);
        setEditingDocument(null);
        setEditorOpen(false);
        setImportOpen(false);
      }
      queryClient.removeQueries({ queryKey: ['knowledge-documents', id] });
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('删除知识库失败'),
  });

  const createDocumentMut = useMutation({
    mutationFn: createKnowledgeDocument,
    onSuccess: () => {
      message.success('文档已创建');
      closeEditor();
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('创建文档失败'),
  });

  const updateDocumentMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: KnowledgeDocumentInput }) =>
      updateKnowledgeDocument(id, input),
    onSuccess: () => {
      message.success('文档已更新');
      closeEditor();
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('更新文档失败'),
  });

  const deleteDocumentMut = useMutation({
    mutationFn: deleteKnowledgeDocument,
    onSuccess: () => {
      message.success('文档已删除');
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('删除文档失败'),
  });

  const importDocumentMut = useMutation({
    mutationFn: ({ knowledgeBaseId, file }: { knowledgeBaseId: number; file: File }) =>
      importKnowledgeDocument(knowledgeBaseId, file),
    onSuccess: () => {
      message.success('文档已导入');
      setImportOpen(false);
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('导入文档失败'),
  });

  function openCreateBase() {
    setEditingBase(null);
    baseForm.resetFields();
    setBaseModalOpen(true);
  }

  function openEditBase(base: KnowledgeBase) {
    setEditingBase(base);
    baseForm.setFieldsValue({ name: base.name, description: base.description });
    setBaseModalOpen(true);
  }

  function submitBase(values: BaseFormValues) {
    const input = {
      name: values.name,
      description: values.description ?? '',
    };

    if (editingBase) {
      updateBaseMut.mutate({ id: editingBase.id, input });
    } else {
      createBaseMut.mutate(input);
    }
  }

  function openCreateDocument() {
    setEditingDocument(null);
    setEditorOpen(true);
  }

  function openEditDocument(document: KnowledgeDocument) {
    setEditingDocument(document);
    setEditorOpen(true);
  }

  function closeEditor() {
    setEditorOpen(false);
    setEditingDocument(null);
  }

  function submitDocument(input: KnowledgeDocumentInput) {
    if (editingDocument) {
      updateDocumentMut.mutate({ id: editingDocument.id, input });
    } else {
      createDocumentMut.mutate(input);
    }
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: isNarrow ? 'minmax(0, 1fr)' : '300px minmax(0, 1fr)',
        gap: 16,
      }}
    >
      <section
        style={{
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: 16,
          minHeight: 520,
        }}
      >
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
          <Text strong>知识库</Text>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreateBase}>
            新建
          </Button>
        </Space>

        {basesQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <Spin />
          </div>
        ) : bases.length === 0 ? (
          <Empty description="还没有知识库" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            dataSource={bases}
            renderItem={(base) => {
              const selected = base.id === selectedBaseId;
              return (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    padding: '10px 8px',
                    borderRadius: 6,
                    background: selected ? '#ecfdf5' : undefined,
                    borderBlockEnd: 0,
                    marginBottom: 4,
                  }}
                  onClick={() => setSelectedBaseId(base.id)}
                  actions={[
                    <Tooltip key="edit" title="重命名">
                      <Button
                        type="text"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={(event) => {
                          event.stopPropagation();
                          openEditBase(base);
                        }}
                      />
                    </Tooltip>,
                    <Tooltip key="delete" title="删除">
                      <Popconfirm
                        title="删除这个知识库？"
                        description="知识库中的所有文档都会被删除。"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={(event) => {
                          event?.stopPropagation();
                          deleteBaseMut.mutate(base.id);
                        }}
                      >
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={(event) => event.stopPropagation()}
                        />
                      </Popconfirm>
                    </Tooltip>,
                  ]}
                >
                  <List.Item.Meta
                    title={<Text strong={selected}>{base.name}</Text>}
                    description={
                      base.description ? (
                        <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
                          {base.description}
                        </Paragraph>
                      ) : (
                        <Text type="secondary">暂无描述</Text>
                      )
                    }
                  />
                </List.Item>
              );
            }}
          />
        )}
      </section>

      <main
        style={{
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: 16,
          minHeight: 520,
        }}
      >
        <Space
          style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}
          align="start"
          direction={isNarrow ? 'vertical' : 'horizontal'}
          wrap
        >
          <div style={{ minWidth: 0, width: isNarrow ? '100%' : undefined }}>
            <Text strong>{selectedBase?.name ?? '请选择知识库'}</Text>
            {selectedBase?.description && (
              <Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 680 }}>
                {selectedBase.description}
              </Paragraph>
            )}
          </div>
          <Space
            wrap
            style={{ width: isNarrow ? '100%' : undefined }}
            direction={isNarrow ? 'vertical' : 'horizontal'}
          >
            <Input.Search
              allowClear
              placeholder="搜索文档"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onSearch={(value) => setSearch(value)}
              style={{ width: isNarrow ? '100%' : 260 }}
              disabled={!selectedBaseId}
            />
            <Button
              icon={<InboxOutlined />}
              disabled={!selectedBaseId}
              onClick={() => setImportOpen(true)}
              style={{ width: isNarrow ? '100%' : undefined }}
            >
              导入
            </Button>
            <Button
              type="primary"
              icon={<FileAddOutlined />}
              disabled={!selectedBaseId}
              onClick={openCreateDocument}
              style={{ width: isNarrow ? '100%' : undefined }}
            >
              新建文档
            </Button>
          </Space>
        </Space>

        {!selectedBaseId ? (
          <Empty description="请先创建或选择知识库" />
        ) : documentsQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        ) : documents.length === 0 ? (
          <Empty description={search.trim() ? '没有匹配的文档' : '还没有文档'} />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {documents.map((document) => (
              <Card
                key={document.id}
                size="small"
                title={document.title}
                extra={
                  <Space>
                    <Tag color={document.source_type === 'upload' ? 'blue' : 'green'}>
                      {SOURCE_TYPE_LABELS[document.source_type] ?? document.source_type}
                    </Tag>
                    <Tooltip title="编辑">
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => openEditDocument(document)}
                      />
                    </Tooltip>
                    <Tooltip title="删除">
                      <Popconfirm
                        title="删除这个文档？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={() => deleteDocumentMut.mutate(document.id)}
                      >
                        <Button type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </Tooltip>
                  </Space>
                }
              >
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {document.source_name && <Text type="secondary">{document.source_name}</Text>}
                  {document.tags.length > 0 && (
                    <Space size={[0, 4]} wrap>
                      {document.tags.map((tag) => (
                        <Tag key={tag}>{tag}</Tag>
                      ))}
                    </Space>
                  )}
                  <Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 0 }}>
                    {document.content || <Text type="secondary">暂无内容</Text>}
                  </Paragraph>
                </Space>
              </Card>
            ))}
          </Space>
        )}
      </main>

      <Modal
        title={editingBase ? '重命名知识库' : '新建知识库'}
        open={baseModalOpen}
        onCancel={() => {
          setBaseModalOpen(false);
          setEditingBase(null);
          baseForm.resetFields();
        }}
        onOk={() => baseForm.submit()}
        okText={editingBase ? '保存' : '创建'}
        cancelText="取消"
        confirmLoading={createBaseMut.isPending || updateBaseMut.isPending}
      >
        <Form form={baseForm} layout="vertical" onFinish={submitBase}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input placeholder="例如：Java 八股文" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="可选，用来说明这个知识库的用途" />
          </Form.Item>
        </Form>
      </Modal>

      {selectedBaseId && (
        <>
          <KnowledgeDocumentEditor
            open={editorOpen}
            document={editingDocument}
            knowledgeBaseId={selectedBaseId}
            saving={createDocumentMut.isPending || updateDocumentMut.isPending}
            onSubmit={submitDocument}
            onClose={closeEditor}
          />
          <KnowledgeImportModal
            open={importOpen}
            uploading={importDocumentMut.isPending}
            onSubmit={(file) => importDocumentMut.mutate({ knowledgeBaseId: selectedBaseId, file })}
            onClose={() => setImportOpen(false)}
          />
        </>
      )}
    </div>
  );
}
