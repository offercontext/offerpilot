import { useEffect } from 'react';
import { Button, Drawer, Form, Grid, Input, Select } from 'antd';
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
  const screens = Grid.useBreakpoint();
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
      title={editing ? '编辑知识文档' : '新建知识文档'}
      open={open}
      onClose={onClose}
      width={screens.md ? 640 : '100%'}
      destroyOnClose
    >
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

        <Button type="primary" htmlType="submit" loading={saving}>
          保存文档
        </Button>
      </Form>
    </Drawer>
  );
}
