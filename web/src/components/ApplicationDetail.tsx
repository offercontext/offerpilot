import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Drawer,
  Typography,
  Tag,
  Timeline,
  Button,
  Form,
  Input,
  Select,
  message,
  Empty,
  Spin,
  Popconfirm,
} from 'antd';
import { RobotOutlined, PlusOutlined, LinkOutlined } from '@ant-design/icons';
import type { Application } from '@/types/application';
import { STATUS_LABELS } from '@/types/application';
import { listNotesByApp, createNote, deleteNote as removeNote } from '@/services/notes';
import { analyzeJD } from '@/services/ai';
import type { CreateNoteInput } from '@/types/note';
import JDAnalyzeModal from './JDAnalyzeModal';

const { Title, Paragraph, Text } = Typography;

const MOOD_OPTIONS = [
  { value: '好', label: '好' },
  { value: '一般', label: '一般' },
  { value: '差', label: '差' },
];

interface ApplicationDetailProps {
  application: Application | null;
  open: boolean;
  onClose: () => void;
}

export default function ApplicationDetail({ application, open, onClose }: ApplicationDetailProps) {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [analyzing, setAnalyzing] = useState(false);
  const [jdModalOpen, setJdModalOpen] = useState(false);

  const notesQuery = useQuery({
    queryKey: ['notes', application?.id],
    queryFn: () => listNotesByApp(application!.id),
    enabled: !!application,
  });

  const invalidateNotes = () => {
    if (application) queryClient.invalidateQueries({ queryKey: ['notes', application.id] });
  };

  const addNote = useMutation({
    mutationFn: (input: CreateNoteInput) => createNote(application!.id, input),
    onSuccess: () => {
      message.success('已添加面试复盘');
      form.resetFields();
      invalidateNotes();
    },
    onError: () => message.error('添加失败'),
  });

  const removeNoteMut = useMutation({
    mutationFn: (id: number) => removeNote(id),
    onSuccess: () => {
      message.success('已删除');
      invalidateNotes();
    },
    onError: () => message.error('删除失败'),
  });

  const handleAnalyze = async () => {
    if (!application) return;
    setAnalyzing(true);
    try {
      // Prefer the saved JD URL; if none, open the modal so the user pastes text.
      if (application.job_url) {
        await analyzeJD({ jd_url: application.job_url, application_id: application.id });
        message.success('JD 分析完成，已保存');
        queryClient.invalidateQueries({ queryKey: ['jd-analyses', application.id] });
      } else {
        setJdModalOpen(true);
      }
    } catch (e: any) {
      const msg = e?.response?.data?.error ?? 'JD 分析失败';
      message.error(msg);
    } finally {
      setAnalyzing(false);
    }
  };

  if (!application) return null;

  return (
    <>
      <Drawer
        title={
          <span>
            {application.company_name} · {application.position_name}
          </span>
        }
        open={open}
        onClose={onClose}
        width={520}
        destroyOnClose
      >
        <div style={{ marginBottom: 16 }}>
          <Tag color="green">{STATUS_LABELS[application.status]}</Tag>
          {application.job_url && (
            <a href={application.job_url} target="_blank" rel="noreferrer" style={{ marginLeft: 8 }}>
              <LinkOutlined /> 查看 JD
            </a>
          )}
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={analyzing}
            onClick={handleAnalyze}
            style={{ marginLeft: 12 }}
          >
            分析 JD
          </Button>
        </div>

        {application.notes && (
          <Paragraph type="secondary">备注：{application.notes}</Paragraph>
        )}

        <Title level={5} style={{ marginTop: 8 }}>
          面试复盘
        </Title>

        <Form
          form={form}
          layout="vertical"
          onFinish={(v) => addNote.mutate(v)}
          style={{ marginBottom: 16 }}
        >
          <div style={{ display: 'flex', gap: 8 }}>
            <Form.Item name="round" style={{ flex: 1 }} label="轮次">
              <Input placeholder="一面" />
            </Form.Item>
            <Form.Item name="date" style={{ flex: 1 }} label="日期">
              <Input placeholder="2026-07-01" />
            </Form.Item>
            <Form.Item name="mood" style={{ flex: 1 }} label="心情">
              <Select options={MOOD_OPTIONS} allowClear placeholder="选择" />
            </Form.Item>
          </div>
          <Form.Item name="questions" label="面试问题">
            <Input.TextArea rows={2} placeholder="被问到的问题…" />
          </Form.Item>
          <Form.Item name="self_reflection" label="自我反思">
            <Input.TextArea rows={2} placeholder="表现如何、哪里可以改…" />
          </Form.Item>
          <Form.Item name="difficulty_points" label="难点/薄弱点">
            <Input.TextArea rows={2} placeholder="哪些知识点没答好" />
          </Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            icon={<PlusOutlined />}
            loading={addNote.isPending}
          >
            添加复盘
          </Button>
        </Form>

        {notesQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 24 }}>
            <Spin />
          </div>
        ) : notesQuery.data && notesQuery.data.length > 0 ? (
          <Timeline
            items={notesQuery.data.map((n) => ({
              color: 'green',
              children: (
                <div
                  key={n.id}
                  style={{ paddingBottom: 8, borderBottom: '1px solid #f0f0f0' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Text strong>
                      {n.round || '未标注轮次'} · {n.date} · 心情 {n.mood || '—'}
                    </Text>
                    <Popconfirm
                      title="删除这条复盘？"
                      onConfirm={() => removeNoteMut.mutate(n.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button type="text" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </div>
                  {n.questions && (
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary">问题：</Text>
                      {n.questions}
                    </div>
                  )}
                  {n.self_reflection && (
                    <div>
                      <Text type="secondary">反思：</Text>
                      {n.self_reflection}
                    </div>
                  )}
                  {n.difficulty_points && (
                    <div>
                      <Text type="secondary">难点：</Text>
                      {n.difficulty_points}
                    </div>
                  )}
                </div>
              ),
            }))}
          />
        ) : (
          <Empty description="还没有面试复盘" />
        )}
      </Drawer>

      <JDAnalyzeModal
        open={jdModalOpen}
        application={application}
        onClose={() => setJdModalOpen(false)}
      />
    </>
  );
}