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
  Modal,
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
import type { PilotActionRequest } from '@/types/chat';
import { STATUS_LABELS } from '@/types/application';
import { listNotesByApp, createNote, deleteNote as removeNote, updateNote } from '@/services/notes';
import { listEvents } from '@/services/events';
import type { CreateNoteInput, InterviewNote } from '@/types/note';
import type { ScheduleEvent } from '@/types/event';
import { EVENT_TYPE_LABELS } from '@/types/event';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import ReviewFormDrawer from './ReviewFormDrawer';
import InterviewReviewProposalDrawer, {
  type InterviewReviewProposalAttemptState,
} from './InterviewReviewProposalDrawer';
import InterviewKnowledgeCaptureDrawer, {
  createInterviewKnowledgeCaptureDraft,
  type InterviewKnowledgeCaptureDraft,
} from './InterviewKnowledgeCaptureDrawer';
import InterviewPreparationProposalDrawer, {
  type InterviewPreparationDraft,
  type InterviewPreparationAttemptState,
  type InterviewPreparationKnowledgeOption,
} from './InterviewPreparationProposalDrawer';
import type { Resume } from '@/types/resume';
import MaterialKitDrawer from './MaterialKitDrawer';
import OpportunityFitReviewDrawer from './OpportunityFitReviewDrawer';
import {
  createOpportunityFitV2Draft,
  type OpportunityFitReview,
  type OpportunityFitV2Draft,
} from '@/types/opportunityFitReview';
import { SourceStateTag } from './ui/SourceStateTag';
import { createPilotAttachmentDragBinding } from './PilotAttachmentHandle';
import { consumeMaterialKitHandoff } from '@/features/pilot/materialKitHandoff';
import {
  getCurrentApplicationJd,
  getApplicationJdVersion,
  listApplicationJdVersions,
  saveApplicationJdVersion,
} from '@/services/applicationJdVersions';
import type { ApplicationJdDraft } from '@/types/applicationJdVersion';
import NextStepSuggestions from './NextStepSuggestions';
import type {
  NextStepDestination,
  NextStepSuggestions as NextStepSuggestionsModel,
  ReadonlyDestination,
  SuggestionSessionState,
} from '@/lib/nextStepSuggestions';
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
  onAskPilot?: (app: Application, action?: PilotActionRequest) => void;
  onOpenPilotOpportunityFit?: (app: Application) => void;
  pilotInterviewReviewApplicationId?: number | null;
  onPilotInterviewReviewFocusConsumed?: () => void;
  pilotInterviewPreparationApplicationId?: number | null;
  pilotInterviewPreparationEventId?: number | null;
  onPilotInterviewPreparationFocusConsumed?: () => void;
  onAttachToPilot?: (attachment: import('@/types/chat').PilotContextAttachment) => void;
  interviewReviewProposalAttempts?: Record<number, InterviewReviewProposalAttemptState>;
  onInterviewReviewProposalAttemptChange?: (
    noteID: number,
    state: InterviewReviewProposalAttemptState | null,
  ) => void;
  onInterviewNoteChanged?: (noteID: number) => void;
  interviewKnowledgeCaptureDrafts?: Record<number, InterviewKnowledgeCaptureDraft>;
  onInterviewKnowledgeCaptureDraftChange?: (noteID: number, draft: InterviewKnowledgeCaptureDraft | null) => void;
  onInterviewKnowledgeCaptureNoteChanged?: (noteID: number) => void;
  resumes?: Resume[];
  interviewPreparationAttempts?: Record<string, InterviewPreparationAttemptState>;
  onInterviewPreparationAttemptChange?: (key: string, state: InterviewPreparationAttemptState | null) => void;
  interviewPreparationDrafts?: Record<string, InterviewPreparationDraft>;
  onInterviewPreparationDraftChange?: (key: string, draft: InterviewPreparationDraft | null) => void;
  interviewPreparationKnowledgeOptions?: InterviewPreparationKnowledgeOption[];
  nextStepSuggestions?: NextStepSuggestionsModel;
  nextStepSessionState?: SuggestionSessionState | null;
  onSetDisposition?: (applicationId: number, suggestionId: string, state: SuggestionSessionState | null) => void;
  onNextStepNavigate?: (destination: NextStepDestination | ReadonlyDestination) => void;
  isNavigationAvailable?: (destination: NextStepDestination | ReadonlyDestination) => boolean;
  onNextStepReadonlyNavigate?: (destination: ReadonlyDestination) => void;
  isReadonlyNavigationAvailable?: (destination: ReadonlyDestination) => boolean;
  applicationJdDraft?: ApplicationJdDraft;
  onApplicationJdDraftChange?: (applicationId: number, patch: Partial<ApplicationJdDraft> | null) => void;
  opportunityFitDraft?: OpportunityFitV2Draft;
  onOpportunityFitDraftChange?: (applicationId: number, patch: Partial<OpportunityFitV2Draft> | null) => void;
}

export default function ApplicationDetail({ application, open, onClose, onMockInterview, onAskPilot, onOpenPilotOpportunityFit, pilotInterviewReviewApplicationId, onPilotInterviewReviewFocusConsumed, pilotInterviewPreparationApplicationId, pilotInterviewPreparationEventId, onPilotInterviewPreparationFocusConsumed, onAttachToPilot, interviewReviewProposalAttempts, onInterviewReviewProposalAttemptChange, onInterviewNoteChanged, interviewKnowledgeCaptureDrafts, onInterviewKnowledgeCaptureDraftChange, onInterviewKnowledgeCaptureNoteChanged, resumes = [], interviewPreparationAttempts, onInterviewPreparationAttemptChange, interviewPreparationDrafts, onInterviewPreparationDraftChange, interviewPreparationKnowledgeOptions = [], nextStepSuggestions, nextStepSessionState = null, onSetDisposition, onNextStepNavigate, isNavigationAvailable, onNextStepReadonlyNavigate, isReadonlyNavigationAvailable, applicationJdDraft, onApplicationJdDraftChange, opportunityFitDraft, onOpportunityFitDraftChange }: ApplicationDetailProps) {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [eventFormOpen, setEventFormOpen] = useState(false);
  const [materialKitOpen, setMaterialKitOpen] = useState(false);
  const [opportunityFitOpen, setOpportunityFitOpen] = useState(false);
  const [materialKitPrefill, setMaterialKitPrefill] = useState<{
    resumeID?: number;
    jdSnapshot?: string;
    jdVersionID?: number;
  }>({});
  const [materialKitApplicationId, setMaterialKitApplicationId] = useState<number | null>(null);
  const [editingNote, setEditingNote] = useState<InterviewNote | null>(null);
  const [reviewFormOpen, setReviewFormOpen] = useState(false);
  const [reviewProposalOpen, setReviewProposalOpen] = useState(false);
  const [knowledgeCaptureOpen, setKnowledgeCaptureOpen] = useState(false);
  const [reviewEventID, setReviewEventID] = useState<number | null>(null);
  const [preparationOpen, setPreparationOpen] = useState(false);
  const [preparationEventID, setPreparationEventID] = useState<number | null>(null);
  const [pilotPreparationChoices, setPilotPreparationChoices] = useState<ScheduleEvent[]>([]);
  const [jdEditorOpen, setJdEditorOpen] = useState(false);
  const [jdHistoryOpen, setJdHistoryOpen] = useState(false);
  const [selectedJdVersion, setSelectedJdVersion] = useState<number | null>(null);

  const applicationJdQuery = useQuery({
    queryKey: ['application-jd-current', application?.id],
    queryFn: () => getCurrentApplicationJd(application!.id),
    enabled: Boolean(application) && open,
  });
  const jdHistoryQuery = useQuery({
    queryKey: ['application-jd-history', application?.id],
    queryFn: () => listApplicationJdVersions(application!.id),
    enabled: Boolean(application) && open && jdHistoryOpen,
  });
  const jdDetailQuery = useQuery({
    queryKey: ['application-jd-detail', application?.id, selectedJdVersion],
    queryFn: () => getApplicationJdVersion(application!.id, selectedJdVersion!),
    enabled: Boolean(application) && open && selectedJdVersion !== null,
  });
  const jdSave = useMutation({
    mutationFn: (draft: ApplicationJdDraft) => saveApplicationJdVersion(application!.id, {
      jd_text: draft.jdText,
      source_url: draft.sourceUrl.trim() || null,
      expected_current_version_id: draft.expectedCurrentVersionId,
      idempotency_key: draft.idempotencyKey!,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['application-jd-current', application?.id] });
      queryClient.invalidateQueries({ queryKey: ['application-jd-history', application?.id] });
      onApplicationJdDraftChange?.(application!.id, null);
      setJdEditorOpen(false);
      message.success('\u5c97\u4f4d\u8d44\u6599\u5df2\u4fdd\u5b58');
    },
    onError: (error: Error & { status?: number; code?: string }) => {
      if (error.code === 'application_jd_stale_current_version') {
        void applicationJdQuery.refetch().then(({ data }) => {
          onApplicationJdDraftChange?.(application!.id, {
            expectedCurrentVersionId: data?.current?.id ?? null,
            idempotencyKey: null,
            pendingOperation: null,
            resultUnknown: false,
          });
        });
        message.error('\u5c97\u4f4d\u8d44\u6599\u5df2\u66f4\u65b0\uff0c\u5df2\u5237\u65b0\u5f53\u524d\u7248\u672c\uff0c\u8bf7\u786e\u8ba4\u540e\u518d\u4fdd\u5b58');
        return;
      }
      if (!error.status || error.status >= 500) {
        onApplicationJdDraftChange?.(application!.id, { resultUnknown: true, pendingOperation: 'save' });
        message.error('\u4fdd\u5b58\u7ed3\u679c\u5f85\u786e\u8ba4\uff0c\u53ef\u4f7f\u7528\u539f\u5c1d\u8bd5\u91cd\u8bd5');
        return;
      }
      onApplicationJdDraftChange?.(application!.id, { idempotencyKey: null, pendingOperation: null, resultUnknown: false });
      message.error('\u5c97\u4f4d\u8d44\u6599\u4e0d\u80fd\u4fdd\u5b58');
    },
  });

  const startJdEditor = () => {
    const current = applicationJdQuery.data?.current;
    const draft = applicationJdDraft;
    onApplicationJdDraftChange?.(application!.id, {
      jdText: draft?.jdText ?? current?.jd_text ?? '',
      sourceUrl: draft?.sourceUrl ?? current?.source_url ?? '',
      expectedCurrentVersionId: draft?.expectedCurrentVersionId ?? current?.id ?? null,
      idempotencyKey: draft?.idempotencyKey ?? null,
      resultUnknown: draft?.resultUnknown ?? false,
      pendingOperation: draft?.pendingOperation ?? null,
    });
    setJdEditorOpen(true);
  };

  const submitJd = () => {
    if (!application || !applicationJdDraft) return;
    const key = applicationJdDraft.idempotencyKey ?? crypto.randomUUID().replace(/[^A-Za-z0-9_-]/g, '').slice(0, 32);
    const draft = { ...applicationJdDraft, idempotencyKey: key, pendingOperation: 'save' as const };
    onApplicationJdDraftChange?.(application.id, draft);
    jdSave.mutate(draft);
  };

  useEffect(() => {
    setMaterialKitPrefill({});
    setMaterialKitOpen(false);
    setMaterialKitApplicationId(null);
  }, [application?.id, open]);

  useEffect(() => {
    if (!application || !open) return;
    const handoff = consumeMaterialKitHandoff(application.id);
    if (!handoff || !handoff.jdVersionId) return;
    setMaterialKitPrefill({
      resumeID: handoff.resumeId,
      jdSnapshot: handoff.jdText,
      jdVersionID: handoff.jdVersionId,
    });
    setMaterialKitApplicationId(application.id);
    setMaterialKitOpen(true);
  }, [application?.id, open]);

  useEffect(() => {
    if (!application || !open || pilotInterviewReviewApplicationId !== application.id) return;
    setEditingNote(null);
    setReviewEventID(null);
    setPreparationOpen(false);
    setPreparationEventID(null);
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

  useEffect(() => {
    if (!application || !open || pilotInterviewPreparationApplicationId !== application.id || !eventsQuery.data) return;
    const interviewEvents = eventsQuery.data.filter((event) => event.event_type === 'interview');
    if (interviewEvents.length === 0) return;
    const requestedEvent = pilotInterviewPreparationEventId == null
      ? null
      : interviewEvents.find((event) => event.id === pilotInterviewPreparationEventId) ?? null;
    if (requestedEvent) {
      setPreparationEventID(requestedEvent.id);
      setPreparationOpen(true);
      onPilotInterviewPreparationFocusConsumed?.();
      return;
    }
    if (interviewEvents.length === 1) {
      setPreparationEventID(interviewEvents[0].id);
      setPreparationOpen(true);
    } else {
      setPilotPreparationChoices(interviewEvents);
    }
    onPilotInterviewPreparationFocusConsumed?.();
  }, [application, eventsQuery.data, open, pilotInterviewPreparationEventId, onPilotInterviewPreparationFocusConsumed, pilotInterviewPreparationApplicationId]);

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
    onSuccess: (_data, variables) => {
      onInterviewNoteChanged?.(variables.id);
      onInterviewKnowledgeCaptureNoteChanged?.(variables.id);
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
    setKnowledgeCaptureOpen(false);
    setReviewEventID(null);
    setPilotPreparationChoices([]);
    setPreparationOpen(false);
    setPreparationEventID(null);
    onClose();
  };

  const openKnowledgeCapture = (note: InterviewNote) => {
    const existing = interviewKnowledgeCaptureDrafts?.[note.id] ?? createInterviewKnowledgeCaptureDraft();
    onInterviewKnowledgeCaptureDraftChange?.(note.id, existing);
    setEditingNote(note);
    setKnowledgeCaptureOpen(true);
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
           if (editingNote) {
             updateNoteMut.mutate({ id: editingNote.id, input });
           } else {
             createEventNoteMut.mutate(input);
           }
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
        initialJdVersionID={materialKitPrefill.jdSnapshot && !materialKitPrefill.jdVersionID
          ? undefined
          : materialKitPrefill.jdVersionID ?? applicationJdQuery.data?.current?.id}
      />
    );
  }

  if (reviewProposalOpen && editingNote) {
    return (
      <InterviewReviewProposalDrawer
        open={reviewProposalOpen}
        note={editingNote}
        eventID={editingNote.application_event_id}
        attemptState={interviewReviewProposalAttempts?.[editingNote.id]}
        onAttemptStateChange={(state) => onInterviewReviewProposalAttemptChange?.(editingNote.id, state)}
        onClose={() => {
          setReviewProposalOpen(false);
          setEditingNote(null);
        }}
      />
    );
  }

  if (preparationOpen && preparationEventID !== null) {
    const preparationKey = `${application.id}:${preparationEventID}`;
    return (
      <InterviewPreparationProposalDrawer
        key={`${application.id}:${preparationEventID}`}
        open
        context={{
          applicationId: application.id,
          eventId: preparationEventID,
          resumeId: 0,
          jdText: applicationJdQuery.data?.current?.jd_text ?? '',
          jdVersionId: applicationJdQuery.data?.current?.id ?? null,
          knowledgeSelections: [],
          userAssertions: [],
        }}
        resumeOptions={resumes}
        knowledgeOptions={interviewPreparationKnowledgeOptions}
        attemptState={interviewPreparationAttempts?.[preparationKey]}
        draft={interviewPreparationDrafts?.[preparationKey]}
        onAttemptStateChange={(state) => onInterviewPreparationAttemptChange?.(preparationKey, state)}
        onDraftChange={(draft) => onInterviewPreparationDraftChange?.(preparationKey, draft)}
        onClose={() => {
          setPreparationOpen(false);
          setPreparationEventID(null);
        }}
      />
    );
  }

  if (knowledgeCaptureOpen && editingNote) {
    return (
      <InterviewKnowledgeCaptureDrawer
        open
        note={editingNote}
        draft={interviewKnowledgeCaptureDrafts?.[editingNote.id] ?? createInterviewKnowledgeCaptureDraft()}
        onDraftChange={(draft) => onInterviewKnowledgeCaptureDraftChange?.(editingNote.id, draft)}
        onClose={() => {
          setKnowledgeCaptureOpen(false);
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
        currentJdText={applicationJdQuery.data?.current?.jd_text ?? ''}
        jdVersionId={applicationJdQuery.data?.current?.id ?? null}
        draft={opportunityFitDraft ?? createOpportunityFitV2Draft(application.id)}
        onDraftChange={(patch) => onOpportunityFitDraftChange?.(application.id, patch)}
        onApplicationMissing={onClose}
        onClose={() => setOpportunityFitOpen(false)}
        onPrepareMaterials={(reviewOrResumeId: OpportunityFitReview | number, jdText: string, jdVersionId?: number) => {
          if (!jdVersionId) return;
          const resumeID = typeof reviewOrResumeId === 'number'
            ? reviewOrResumeId
            : reviewOrResumeId.source.resume.id;
          setMaterialKitPrefill({ resumeID, jdSnapshot: jdText, jdVersionID: jdVersionId });
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
      <Modal
        open={pilotPreparationChoices.length > 1}
        title="选择要准备的面试"
        footer={null}
        onCancel={() => setPilotPreparationChoices([])}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {pilotPreparationChoices.map((event) => (
            <Button
              key={event.id}
              block
              onClick={() => {
                setPreparationEventID(event.id);
                setPreparationOpen(true);
                setPilotPreparationChoices([]);
              }}
            >
              {event.subtype || '面试'} · {event.scheduled_at}
            </Button>
          ))}
        </Space>
      </Modal>
      <Modal
        open={jdEditorOpen}
        title={'\u6295\u9012\u5c97\u4f4d\u8d44\u6599'}
        okText={applicationJdDraft?.resultUnknown ? '\u4f7f\u7528\u539f\u5c1d\u8bd5\u91cd\u8bd5' : '\u4fdd\u5b58\u5c97\u4f4d\u8d44\u6599'}
        cancelText={'\u53d6\u6d88'}
        confirmLoading={jdSave.isPending}
        onOk={submitJd}
        onCancel={() => setJdEditorOpen(false)}
      >
        <Input.TextArea
          rows={10}
          value={applicationJdDraft?.jdText ?? applicationJdQuery.data?.current?.jd_text ?? ''}
          disabled={Boolean(applicationJdDraft?.resultUnknown)}
          onChange={(event) => onApplicationJdDraftChange?.(application!.id, { jdText: event.target.value })}
          placeholder={'\u7c98\u8d34\u5c97\u4f4d\u63cf\u8ff0'}
        />
        <Input
          style={{ marginTop: 12 }}
          value={applicationJdDraft?.sourceUrl ?? applicationJdQuery.data?.current?.source_url ?? ''}
          disabled={Boolean(applicationJdDraft?.resultUnknown)}
          onChange={(event) => onApplicationJdDraftChange?.(application!.id, { sourceUrl: event.target.value })}
          placeholder={'\u6765\u6e90 URL\uff08\u4ec5\u5c55\u793a\uff0c\u4e0d\u4f1a\u8bbf\u95ee\uff09'}
        />
        {applicationJdDraft?.resultUnknown && (
          <Paragraph type="warning" style={{ marginTop: 12, marginBottom: 0 }}>
            {'\u4fdd\u5b58\u7ed3\u679c\u5f85\u786e\u8ba4\uff0c\u8bf7\u4f7f\u7528\u539f\u5c1d\u8bd5\u91cd\u8bd5\u3002'}
          </Paragraph>
        )}
      </Modal>
      <Modal
        open={jdHistoryOpen}
        title={'\u5c97\u4f4d\u8d44\u6599\u5386\u53f2'}
        footer={null}
        onCancel={() => { setJdHistoryOpen(false); setSelectedJdVersion(null); }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          {jdHistoryQuery.isLoading ? <Spin /> : (jdHistoryQuery.data ?? []).map((version) => (
            <Button key={version.id} block type={selectedJdVersion === version.id ? 'primary' : 'default'} onClick={() => setSelectedJdVersion(version.id)}>
              v{version.version_number} · {version.source_kind} · {version.preview.slice(0, 80)}
            </Button>
          ))}
          {selectedJdVersion !== null && jdDetailQuery.data && (
            <div style={{ whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto', border: '1px solid #e2e8f0', padding: 12, borderRadius: 8 }}>
              {jdDetailQuery.data.jd_text}
            </div>
          )}
        </Space>
      </Modal>
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
            <SourceStateTag state="current" detail="当前投递" />
          </div>
        </div>

        {nextStepSuggestions && onSetDisposition && onNextStepNavigate && (
          <NextStepSuggestions
            applicationId={application.id}
            suggestions={nextStepSuggestions}
            sessionState={nextStepSessionState}
            onSetDisposition={onSetDisposition}
            onNavigate={onNextStepNavigate}
            isNavigationAvailable={isNavigationAvailable}
            onNavigateReadonly={onNextStepReadonlyNavigate}
            isReadonlyNavigationAvailable={isReadonlyNavigationAvailable}
          />
        )}

        <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 14, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <Text strong>{'\u6295\u9012\u5c97\u4f4d\u8d44\u6599'}</Text>
            <Space>
              <Button size="small" onClick={() => { setJdHistoryOpen(true); setSelectedJdVersion(null); }}>{'\u67e5\u770b\u5386\u53f2'}</Button>
              <Button size="small" type="primary" onClick={startJdEditor}>{applicationJdQuery.data?.current ? '\u66f4\u65b0 JD' : '\u6dfb\u52a0 JD'}</Button>
              {onAskPilot && (
                <Button
                  size="small"
                  onClick={() => onAskPilot(application, { type: 'application_jd_save' })}
                >
                  {applicationJdQuery.data?.current ? '更新岗位资料' : '保存岗位资料'}
                </Button>
              )}
            </Space>
          </div>
          {applicationJdQuery.isLoading ? <Spin size="small" /> : applicationJdQuery.data?.current ? (
            <>
            <Paragraph ellipsis={{ rows: 3 }} style={{ margin: '10px 0 0', whiteSpace: 'pre-wrap' }}>
              {applicationJdQuery.data.current.jd_text}
            </Paragraph>
            <Space size={8} style={{ marginTop: 8 }}>
              <Text type="secondary">{'\u6765\u6e90\uff1a'}{applicationJdQuery.data.current.source_url}</Text>
              <Button
                size="small"
                onClick={() => {
                  void navigator.clipboard?.writeText(applicationJdQuery.data!.current!.source_url!);
                }}
              >
                {'\u590d\u5236\u6765\u6e90'}
              </Button>
            </Space>
            </>
          ) : <Text type="secondary">{'\u5c1a\u672a\u786e\u8ba4\u5c97\u4f4d\u63cf\u8ff0'}</Text>}
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
                  <Space size={4}>
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
                    {linkedNote && (
                      <Button size="small" type="link" onClick={() => openKnowledgeCapture(linkedNote)}>
                        沉淀知识
                      </Button>
                    )}
                    <Button
                      size="small"
                      type="link"
                      onClick={() => {
                        setPreparationEventID(event.id);
                        setPreparationOpen(true);
                      }}
                    >
                      面试准备建议
                    </Button>
                  </Space>
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
                      <Button type="text" size="small" onClick={() => openKnowledgeCapture(n)}>
                        沉淀知识
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
      </section>

    </>
  );
}
