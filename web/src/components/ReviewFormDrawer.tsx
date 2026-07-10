import { useEffect } from 'react';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Button, Form, Input, Select, Space } from 'antd';
import type { Application } from '@/types/application';
import type { CreateNoteInput, InterviewNote } from '@/types/note';

const MOOD_OPTIONS = [
  { value: 'good', label: '好' },
  { value: 'normal', label: '一般' },
  { value: 'bad', label: '差' },
];

interface Props {
  open: boolean;
  applications: Application[];
  initialApplication?: Application | null;
  note?: InterviewNote | null;
  saving?: boolean;
  onSubmit: (input: CreateNoteInput) => void;
  onClose: () => void;
}

export default function ReviewFormDrawer({
  open,
  applications,
  initialApplication,
  note,
  saving = false,
  onSubmit,
  onClose,
}: Props) {
  const [form] = Form.useForm<CreateNoteInput>();
  const editing = !!note;

  useEffect(() => {
    if (!open) return;

    if (note) {
      form.setFieldsValue({
        application_id: note.application_id,
        company: note.company,
        position: note.position,
        round: note.round,
        date: note.date,
        questions: note.questions,
        self_reflection: note.self_reflection,
        difficulty_points: note.difficulty_points,
        mood: note.mood,
      });
      return;
    }

    form.resetFields();
    if (initialApplication) {
      form.setFieldsValue({
        application_id: initialApplication.id,
        company: initialApplication.company_name,
        position: initialApplication.position_name,
      });
    }
  }, [open, note, initialApplication, form]);

  function handleApplicationChange(appID?: number) {
    const app = applications.find((item) => item.id === appID);
    if (!app) return;

    form.setFieldsValue({
      company: app.company_name,
      position: app.position_name,
    });
  }

  if (!open) return null;

  return (
    <section aria-label={editing ? '编辑面试复盘' : '新建面试复盘'}>
      <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
        <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={onClose}
          style={{ width: 'fit-content', height: 'auto', padding: 0 }}
        >
          返回上一层
        </Button>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} align="center" wrap>
          <h2 style={{ margin: 0 }}>{editing ? '编辑面试复盘' : '新建面试复盘'}</h2>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" loading={saving} onClick={() => form.submit()}>
              保存复盘
            </Button>
          </Space>
        </Space>
      </div>
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="application_id" label="关联投递">
          <Select
            allowClear
            showSearch
            placeholder="可选"
            optionFilterProp="label"
            onChange={handleApplicationChange}
            options={applications.map((app) => ({
              value: app.id,
              label: `${app.company_name} / ${app.position_name}`,
            }))}
          />
        </Form.Item>

        <Space style={{ width: '100%' }} align="start" wrap>
          <Form.Item
            name="company"
            label="公司"
            rules={[{ required: true, message: '请输入公司' }]}
            style={{ flex: '1 1 220px', minWidth: 220 }}
          >
            <Input placeholder="公司" />
          </Form.Item>
          <Form.Item name="position" label="岗位" style={{ flex: '1 1 220px', minWidth: 220 }}>
            <Input placeholder="岗位" />
          </Form.Item>
        </Space>

        <Space style={{ width: '100%' }} align="start" wrap>
          <Form.Item name="round" label="轮次" style={{ flex: '1 1 140px', minWidth: 140 }}>
            <Input placeholder="一面" />
          </Form.Item>
          <Form.Item name="date" label="日期" style={{ flex: '1 1 140px', minWidth: 140 }}>
            <Input placeholder="2026-07-01" />
          </Form.Item>
          <Form.Item name="mood" label="心情" style={{ flex: '1 1 140px', minWidth: 140 }}>
            <Select options={MOOD_OPTIONS} allowClear placeholder="选择" />
          </Form.Item>
        </Space>

        <Form.Item name="questions" label="面试问题">
          <Input.TextArea rows={4} placeholder="记录被问到的问题" />
        </Form.Item>
        <Form.Item name="self_reflection" label="自我反思">
          <Input.TextArea rows={4} placeholder="表现如何，哪里可以改进" />
        </Form.Item>
        <Form.Item name="difficulty_points" label="难点/薄弱点">
          <Input.TextArea rows={4} placeholder="哪些知识点没答好" />
        </Form.Item>
      </Form>
    </section>
  );
}
