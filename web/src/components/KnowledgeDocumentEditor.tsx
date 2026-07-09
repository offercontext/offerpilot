import { useEffect } from 'react';
import { Button, Form, Input, Select, Space } from 'antd';
import type { KnowledgeDocument, KnowledgeDocumentInput } from '@/types/knowledge';

interface Props {
  open: boolean;
  document: KnowledgeDocument | null;
  saving?: boolean;
  onSubmit: (input: KnowledgeDocumentInput) => void;
  onClose: () => void;
}

type FormValues = {
  title: string;
  content?: string;
  tags?: string[];
};

export default function KnowledgeDocumentEditor({
  open,
  document,
  saving = false,
  onSubmit,
  onClose,
}: Props) {
  const [form] = Form.useForm<FormValues>();
  const editing = !!document;

  useEffect(() => {
    if (!open) return;

    if (document) {
      form.setFieldsValue({
        title: document.title,
        content: document.content,
        tags: document.tags ?? [],
      });
      return;
    }

    form.resetFields();
  }, [open, document, form]);

  function handleFinish(values: FormValues) {
    onSubmit({
      title: values.title,
      content: values.content ?? '',
      tags: values.tags ?? [],
    });
  }

  if (!open) return null;

  return (
    <section aria-label={editing ? '编辑知识文档' : '新建知识文档'}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
        <div>
          <Button type="link" style={{ height: 'auto', padding: 0 }} onClick={onClose}>
            返回知识库
          </Button>
          <h2 style={{ margin: '8px 0 0' }}>{editing ? '编辑知识文档' : '新建知识文档'}</h2>
        </div>
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={() => form.submit()}>
            保存文档
          </Button>
        </Space>
      </div>
      <Form form={form} layout="vertical" onFinish={handleFinish}>
        <Form.Item
          name="title"
          label="标题"
          rules={[{ required: true, message: '请输入文档标题' }]}
        >
          <Input placeholder="例如：JVM 内存模型" />
        </Form.Item>

        <Form.Item name="tags" label="标签">
          <Select mode="tags" placeholder="添加标签" tokenSeparators={[',']} />
        </Form.Item>

        <Form.Item name="content" label="内容">
          <Input.TextArea rows={16} placeholder="在这里编写或粘贴学习资料、八股文、面试笔记等内容" />
        </Form.Item>
      </Form>
    </section>
  );
}
