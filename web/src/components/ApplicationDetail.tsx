import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
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
import {
  ArrowLeftOutlined,
  CalendarOutlined,
  RobotOutlined,
  PlusOutlined,
  AudioOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import { STATUS_LABELS } from '@/types/application';
import { listNotesByApp, createNote, deleteNote as removeNote, updateNote } from '@/services/notes';
import { listEvents } from '@/services/events';
import type { CreateNoteInput, InterviewNote } from '@/types/note';
import { EVENT_TYPE_LABELS } from '@/types/event';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import ReviewFormDrawer from './ReviewFormDrawer';
import InterviewReviewProposalDrawer from './InterviewReviewProposalDrawer';
import MaterialKitDrawer from './MaterialKitDrawer';
import OpportunityFitReviewDrawer from './OpportunityFitReviewDrawer';
import type { OpportunityFitReview } from '@/types/opportunityFitReview';
import { createPilotAttachmentDragBinding } from './PilotAttachmentHandle';
import { consumeMaterialKitHandoff } from '@/features/pilot/materialKitHandoff';
import styles from './ApplicationDetail.module.css';

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
  onMockInterview?: (app: Application) => void;
  onAskPilot?: (app: Application) => void;
  onOpenPilotOpportunityFit?: (app: Application) => void;
  pilotInterviewReviewApplicationId?: number | null;
  onPilotInterviewReviewFocusConsumed?: () => void;
  onAttachToPilot?: (attachment: import('@/types/chat').PilotContextAttachment) => void;
}

export default function ApplicationDetail({ application, open, onClose, onMockInterview, onAskPilot, onOpenPilotOpportunityFit, pilotInterviewReviewApplicationId, onPilotInterviewReviewFocusConsumed, onAttachToPilot }: ApplicationDetailProps) {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [eventFormOpen, setEventFormOpen] = useState(false);
  const [materialKitOpen, setMaterialKitOpen] = useState(false);
  const [opportunityFitOpen, setOpportunityFitOpen] = useState(false);
  const [materialKitPrefill, setMaterialKitPrefill] = useState<{
    resumeID?: number;
    jdSnapshot?: string;
  }>({});
  const [materialKitApplicationId, setMaterialKitApplicationId] = useState<number | null>(null);
  const [editingNote, setEditingNote] = useState<InterviewNote | null>(null);
  const [reviewFormOpen, setReviewFormOpen] = useState(false);
  const [reviewProposalOpen, setReviewProposalOpen] = useState(false);
  const [reviewEventID, setReviewEventID] = useState<number | null>(null);

  useEffect(() => {
    setMaterialKitPrefill({});
    setMaterialKitOpen(false);
    setMaterialKitApplicationId(null);
    if (!application || !open) return;
    const handoff = consumeMaterialKitHandoff(application.id);
    if (!handoff) return;
    setMaterialKitPrefill({ resumeID: handoff.resumeId, jdSnapshot: handoff.jdText });
    setMaterialKitApplicationId(application.id);
    setMaterialKitOpen(true);
  }, [application?.id, open]);

  useEffect(() => {
    if (!application || !open || pilotInterviewReviewApplicationId !== application.id) return;
    setEditingNote(null);
    setReviewEventID(null);
    setReviewFormOpen(true);
    onPilotInterviewReviewFocusConsumed?.();
  }, [application, open, pilotInterviewReviewApplicationId, onPilotInterviewReviewFocusConsumed]);

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
      setReviewFormOpen(false);
      setReviewEventID(null);
      invalidateNotes();
    },
    onError: () => message.error('更新失败'),
  });

  const createEventNoteMut = useMutation({
    mutationFn: (input: CreateNoteInput) => createNote(application!.id, input),
    onSuccess: () => {
      message.success('已保存面试复盘');
      setReviewFormOpen(false);
      setReviewEventID(null);
      invalidateNotes();
    },
    onError: () => message.error('保存复盘失败'),
  });

  const closeDetail = () => {
    setEventFormOpen(false);
    setMaterialKitOpen(false);
    setMaterialKitApplicationId(null);
    setOpportunityFitOpen(false);
    setMaterialKitPrefill({});
    setEditingNote(null);
    setReviewFormOpen(false);
    setReviewProposalOpen(false);
    setReviewEventID(null);
    onClose();
  };

  if (!application || !open) return null;

  if (eventFormOpen) {
    return (
      <ScheduleEventForm
        open={eventFormOpen}
        applications={[application]}
        initialApplication={application}
        onClose={() => setEventFormOpen(false)}
      />
    );
  }

  if (reviewFormOpen) {
    return (
      <ReviewFormDrawer
        open={reviewFormOpen}
        applications={[application]}
        initialApplication={application}
        note={editingNote}
        initialEventID={reviewEventID}
        saving={updateNoteMut.isPending || createEventNoteMut.isPending}
        onSubmit={(input) => {
          if (editingNote) updateNoteMut.mutate({ id: editingNote.id, input });
          else createEventNoteMut.mutate(input);
        }}
        onClose={() => {
          setReviewFormOpen(false);
          setEditingNote(null);
          setReviewEventID(null);
        }}
      />
    );
  }

  if (materialKitOpen && materialKitApplicationId === application.id) {
    return (
      <MaterialKitDrawer
        application={application}
        open={materialKitOpen}
        onClose={() => {
          setMaterialKitOpen(false);
          setMaterialKitApplicationId(null);
          setMaterialKitPrefill({});
        }}
        initialResumeID={materialKitPrefill.resumeID}
        initialJdSnapshot={materialKitPrefill.jdSnapshot}
      />
    );
  }

  if (reviewProposalOpen && editingNote) {
    return (
      <InterviewReviewProposalDrawer
        open={reviewProposalOpen}
        note={editingNote}
        eventID={editingNote.application_event_id}
        onClose={() => {
          setReviewProposalOpen(false);
          setEditingNote(null);
        }}
      />
    );
  }

  if (opportunityFitOpen) {
    return (
      <OpportunityFitReviewDrawer
        application={application}
        open={opportunityFitOpen}
        onClose={() => setOpportunityFitOpen(false)}
        onPrepareMaterials={(review: OpportunityFitReview, jdText: string) => {
          setMaterialKitPrefill({ resumeID: review.source.resume.id, jdSnapshot: jdText });
          setMaterialKitApplicationId(application.id);
          setOpportunityFitOpen(false);
          setMaterialKitOpen(true);
        }}
      />
    );
  }

  const applicationDragBinding = onAttachToPilot
    ? createPilotAttachmentDragBinding({
        kind: 'application',
        id: String(application.id),
        label: `${application.company_name} · ${application.position_name}`,
      })
    : undefined;

  return (
    <>
      <section className={styles.detailWorkspace} {...applicationDragBinding}>
        <div className={styles.header}>
          <Button type="link" className={styles.backButton} icon={<ArrowLeftOutlined />} onClick={closeDetail}>
            返回上一层
          </Button>
          <div className={styles.titleRow}>
            <Title level={3} className={styles.title}>
              {application.company_name} · {application.position_name}
            </Title>
            <Tag color="green">{STATUS_LABELS[application.status]}</Tag>
          </div>
        </div>

        <div className={styles.actionRow}>
          {onAskPilot && (
            <Button icon={<RobotOutlined />} onClick={() => onAskPilot(application)}>
              问 Pilot
            </Button>
          )}
          {onOpenPilotOpportunityFit && (
            <Button onClick={() => onOpenPilotOpportunityFit(application)} style={{ marginLeft: 8 }}>
              在 Pilot 中评估
            </Button>
          )}
          <Button
            icon={<FileTextOutlined />}
            onClick={() => {
              setMaterialKitApplicationId(application.id);
              setMaterialKitOpen(true);
            }}
            style={{ marginLeft: 8 }}
          >
            材料包
          </Button>
          <Button onClick={() => setOpportunityFitOpen(true)} style={{ marginLeft: 8 }}>
            岗位决策漏斗
          </Button>
          {onMockInterview && (
            <Button
              icon={<AudioOutlined />}
              onClick={() => onMockInterview(application)}
              style={{ marginLeft: 8 }}
            >
              模拟面试
            </Button>
          )}
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
            {eventsQuery.data.map((event) => {
              const linkedNote = notesQuery.data?.find((note) => note.application_event_id === event.id);
              return (
              <div key={event.id} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <Text strong>{EVENT_TYPE_LABELS[event.event_type]}</Text>
                  <Text type="secondary">{dayjs(event.scheduled_at).format('YYYY-MM-DD HH:mm')}</Text>
                </div>
                <div style={{ color: '#64748b', fontSize: 13, marginTop: 4 }}>
                  时长 {event.duration_minutes} 分钟{event.location ? ` · ${event.location}` : ''}
                </div>
                {event.event_type === 'interview' && (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => {
                      setReviewEventID(event.id);
                      setEditingNote(linkedNote ?? null);
                      if (linkedNote) setReviewProposalOpen(true);
                      else setReviewFormOpen(true);
                    }}
                  >
                    {linkedNote ? '查看复盘' : '记录复盘'}
                  </Button>
                )}
              </div>
              );
            })}
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
                      <Button
                        type="text"
                        size="small"
                        onClick={() => {
                          setEditingNote(n);
                          setReviewEventID(n.application_event_id ?? null);
                          setReviewFormOpen(true);
                        }}
                      >
                        编辑
                      </Button>
                      {n.application_event_id != null && (
                        <Button
                          type="text"
                          size="small"
                          onClick={() => {
                            setEditingNote(n);
                            setReviewProposalOpen(true);
                          }}
                        >
                          复盘建议
                        </Button>
                      )}
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
      </section>

    </>
  );
}
