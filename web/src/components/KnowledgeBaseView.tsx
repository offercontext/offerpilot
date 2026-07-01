import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Card,
  Empty,
  Form,
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

export default function KnowledgeBaseView() {
  const queryClient = useQueryClient();
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
      message.success('Knowledge base created');
      setBaseModalOpen(false);
      setEditingBase(null);
      baseForm.resetFields();
      setSelectedBaseId(base.id);
      invalidateBases();
    },
    onError: () => message.error('Failed to create knowledge base'),
  });

  const updateBaseMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: KnowledgeBaseInput }) =>
      updateKnowledgeBase(id, input),
    onSuccess: () => {
      message.success('Knowledge base updated');
      setBaseModalOpen(false);
      setEditingBase(null);
      baseForm.resetFields();
      invalidateBases();
    },
    onError: () => message.error('Failed to update knowledge base'),
  });

  const deleteBaseMut = useMutation({
    mutationFn: deleteKnowledgeBase,
    onSuccess: (_, id) => {
      message.success('Knowledge base deleted');
      if (selectedBaseId === id) {
        setSelectedBaseId(undefined);
      }
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('Failed to delete knowledge base'),
  });

  const createDocumentMut = useMutation({
    mutationFn: createKnowledgeDocument,
    onSuccess: () => {
      message.success('Document created');
      closeEditor();
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('Failed to create document'),
  });

  const updateDocumentMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: KnowledgeDocumentInput }) =>
      updateKnowledgeDocument(id, input),
    onSuccess: () => {
      message.success('Document updated');
      closeEditor();
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('Failed to update document'),
  });

  const deleteDocumentMut = useMutation({
    mutationFn: deleteKnowledgeDocument,
    onSuccess: () => {
      message.success('Document deleted');
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('Failed to delete document'),
  });

  const importDocumentMut = useMutation({
    mutationFn: ({ knowledgeBaseId, file }: { knowledgeBaseId: number; file: File }) =>
      importKnowledgeDocument(knowledgeBaseId, file),
    onSuccess: () => {
      message.success('Document imported');
      setImportOpen(false);
      invalidateBases();
      invalidateDocs();
    },
    onError: () => message.error('Failed to import document'),
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
    <div style={{ display: 'grid', gridTemplateColumns: '300px minmax(0, 1fr)', gap: 16 }}>
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
          <Text strong>Knowledge Bases</Text>
          <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreateBase}>
            New
          </Button>
        </Space>

        {basesQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}>
            <Spin />
          </div>
        ) : bases.length === 0 ? (
          <Empty description="No knowledge bases yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
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
                    <Tooltip key="edit" title="Rename">
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
                    <Tooltip key="delete" title="Delete">
                      <Popconfirm
                        title="Delete this knowledge base?"
                        description="All documents in this base will be deleted."
                        okText="Delete"
                        cancelText="Cancel"
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
                        <Text type="secondary">No description</Text>
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
          wrap
        >
          <div>
            <Text strong>{selectedBase?.name ?? 'Select a knowledge base'}</Text>
            {selectedBase?.description && (
              <Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 680 }}>
                {selectedBase.description}
              </Paragraph>
            )}
          </div>
          <Space wrap>
            <Input.Search
              allowClear
              placeholder="Search documents"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onSearch={(value) => setSearch(value)}
              style={{ width: 260 }}
              disabled={!selectedBaseId}
            />
            <Button
              icon={<InboxOutlined />}
              disabled={!selectedBaseId}
              onClick={() => setImportOpen(true)}
            >
              Import
            </Button>
            <Button
              type="primary"
              icon={<FileAddOutlined />}
              disabled={!selectedBaseId}
              onClick={openCreateDocument}
            >
              New document
            </Button>
          </Space>
        </Space>

        {!selectedBaseId ? (
          <Empty description="Create or select a knowledge base" />
        ) : documentsQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        ) : documents.length === 0 ? (
          <Empty description={search.trim() ? 'No matching documents' : 'No documents yet'} />
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
                      {document.source_type}
                    </Tag>
                    <Tooltip title="Edit">
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => openEditDocument(document)}
                      />
                    </Tooltip>
                    <Tooltip title="Delete">
                      <Popconfirm
                        title="Delete this document?"
                        okText="Delete"
                        cancelText="Cancel"
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
                    {document.content || <Text type="secondary">No content</Text>}
                  </Paragraph>
                </Space>
              </Card>
            ))}
          </Space>
        )}
      </main>

      <Modal
        title={editingBase ? 'Rename knowledge base' : 'New knowledge base'}
        open={baseModalOpen}
        onCancel={() => {
          setBaseModalOpen(false);
          setEditingBase(null);
          baseForm.resetFields();
        }}
        onOk={() => baseForm.submit()}
        confirmLoading={createBaseMut.isPending || updateBaseMut.isPending}
      >
        <Form form={baseForm} layout="vertical" onFinish={submitBase}>
          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: 'Please enter a name' }]}
          >
            <Input placeholder="Knowledge base name" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={3} placeholder="Optional description" />
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
