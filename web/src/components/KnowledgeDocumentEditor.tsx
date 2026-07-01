import { useEffect } from 'react';
import { Button, Drawer, Form, Input, Select } from 'antd';
import type { KnowledgeDocument, KnowledgeDocumentInput } from '@/types/knowledge';

interface Props {
  open: boolean;
  document: KnowledgeDocument | null;
  knowledgeBaseId: number;
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
  knowledgeBaseId,
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
      knowledge_base_id: knowledgeBaseId,
      title: values.title,
      content: values.content ?? '',
      tags: values.tags ?? [],
    });
  }

  return (
    <Drawer
      title={editing ? 'Edit knowledge document' : 'New knowledge document'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={handleFinish}>
        <Form.Item
          name="title"
          label="Title"
          rules={[{ required: true, message: 'Please enter a title' }]}
        >
          <Input placeholder="Document title" />
        </Form.Item>

        <Form.Item name="tags" label="Tags">
          <Select mode="tags" placeholder="Add tags" tokenSeparators={[',']} />
        </Form.Item>

        <Form.Item name="content" label="Content">
          <Input.TextArea rows={16} placeholder="Write or paste knowledge content" />
        </Form.Item>

        <Button type="primary" htmlType="submit" loading={saving}>
          Save document
        </Button>
      </Form>
    </Drawer>
  );
}
