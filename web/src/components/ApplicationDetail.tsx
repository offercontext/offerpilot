import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Drawer,
  Typography,
  Tag,
  Timeline,
  Button,
  Divider,
  Form,
  Input,
  Select,
  message,
  Empty,
  Spin,
  Popconfirm,
  Space,
} from 'antd';
import { CalendarOutlined, RobotOutlined, PlusOutlined, LinkOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import { STATUS_LABELS } from '@/types/application';
import { listNotesByApp, createNote, deleteNote as removeNote, updateNote } from '@/services/notes';
import { listEvents } from '@/services/events';
import { analyzeJD } from '@/services/ai';
import type { CreateNoteInput, InterviewNote } from '@/types/note';
import { EVENT_TYPE_LABELS } from '@/types/event';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import JDAnalyzeModal from './JDAnalyzeModal';
import ReviewFormDrawer from './ReviewFormDrawer';

const { Title, Paragraph, Text } = Typography;

const MOOD_OPTIONS = [
  { value: 'good', label: '好' },
  { value: 'normal', label: '一般' },
  { value: 'bad', label: '差' },
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
  const [eventFormOpen, setEventFormOpen] = useState(false);
  const [editingNote, setEditingNote] = useState<InterviewNote | null>(null);

  const notesQuery = useQuery({
    queryKey: ['notes', application?.id],
    queryFn: () => listNotesByApp(application!.id),
    enabled: !!application,
  });

  const eventsQuery = useQuery({
    queryKey: ['events', application?.id],
    queryFn: () => listEvents({ application_id: application!.id }),
    enabled: !!application && open,
  });

  const invalidateNotes = () => {
    if (application) queryClient.invalidateQueries({ queryKey: ['notes', application.id] });
    queryClient.invalidateQueries({ queryKey: ['notes', 'all'] });
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

  const updateNoteMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: CreateNoteInput }) => updateNote(id, input),
    onSuccess: () => {
      message.success('已更新面试复盘');
      setEditingNote(null);
      invalidateNotes();
    },
    onError: () => message.error('更新失败'),
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
        onClose={() => {
          setEventFormOpen(false);
          setEditingNote(null);
          onClose();
        }}
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

        <Divider />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <Title level={5} style={{ margin: 0 }}>
            <CalendarOutlined /> 日程
          </Title>
          <Button size="small" icon={<PlusOutlined />} onClick={() => setEventFormOpen(true)}>
            安排日程
          </Button>
        </div>
        {eventsQuery.isLoading ? (
          <div style={{ textAlign: 'center', padding: 16 }}>
            <Spin />
          </div>
        ) : eventsQuery.data && eventsQuery.data.length > 0 ? (
          <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
            {eventsQuery.data.map((event) => (
              <div key={event.id} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <Text strong>{EVENT_TYPE_LABELS[event.event_type]}</Text>
                  <Text type="secondary">{dayjs(event.scheduled_at).format('YYYY-MM-DD HH:mm')}</Text>
                </div>
                <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
                  时长 {event.duration_minutes} 分钟{event.location ? ` · ${event.location}` : ''}
                </div>
              </div>
            ))}
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无笔试、面试或测评日程" style={{ marginBottom: 16 }} />
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
                    <Space size={4}>
                      <Button type="text" size="small" onClick={() => setEditingNote(n)}>
                        编辑
                      </Button>
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
                    </Space>
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
      <ScheduleEventForm
        open={eventFormOpen}
        applications={[application]}
        initialApplication={application}
        onClose={() => setEventFormOpen(false)}
      />
      <ReviewFormDrawer
        open={!!editingNote}
        applications={[application]}
        initialApplication={application}
        note={editingNote}
        saving={updateNoteMut.isPending}
        onSubmit={(input) => {
          if (editingNote) updateNoteMut.mutate({ id: editingNote.id, input });
        }}
        onClose={() => setEditingNote(null)}
      />
    </>
  );
}
