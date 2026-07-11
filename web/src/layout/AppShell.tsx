import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Layout, Spin, Tabs, message } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { ONBOARDING_QUERY_KEY } from '@/services/onboarding';
import { uploadResume } from '@/services/resumes';
import type { Application } from '@/types/application';
import type { ChatStartRequest, PilotContextAttachment } from '@/types/chat';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeUploadModal from '@/components/ResumeUploadModal';
import ChatPanel from '@/components/ChatPanel';
import type { EvidenceTarget } from '@/components/ChatPanel/model';
import AISettingsDrawer from '@/components/AISettingsDrawer';
import CommandPalette from './CommandPalette';
import { moduleTabsForView, type ViewMode } from './navigation';
import {
  derivePipelineInsights,
  toLegacyActionItems,
  type PipelineInsight,
} from '@/lib/pipelineInsights';
import { getPracticeStats } from '@/services/questions';
import { buildPilotPageContext } from '@/lib/pilotPageContext';
import { PilotAttachmentProvider } from '@/features/pilot/PilotAttachmentContext';
import {
  usePilotAttachmentStore,
  type PilotAttachmentConversationKey,
} from '@/features/pilot/PilotAttachmentContext';
import { retainPilotAttachmentKey } from '@/features/pilot/attachmentHandoff';
import dayjs from 'dayjs';

const { Content } = Layout;

const KanbanBoard = lazy(() => import('@/components/KanbanBoard'));
const ApplicationListView = lazy(() => import('@/components/ApplicationListView'));
const CalendarView = lazy(() => import('@/components/CalendarView'));
const KnowledgeLibraryView = lazy(() => import('@/components/KnowledgeLibraryView'));
const QuestionBankView = lazy(() => import('@/components/QuestionBankView'));
const OfferCenterView = lazy(() => import('@/components/OfferCenterView'));
const DashboardView = lazy(() => import('@/features/dashboard/DashboardView'));
const RemindersView = lazy(() => import('@/features/reminders/RemindersView'));
const InterviewV01View = lazy(() => import('@/components/InterviewV01View'));
const ResumeLibraryView = lazy(() => import('@/components/ResumeLibraryView'));
const SettingsView = lazy(() => import('@/components/SettingsView'));

class ViewErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
          <div style={{ marginBottom: 16 }}>View failed to load.</div>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      );
    }

    return this.props.children;
  }
}

function computeStreak(apps: Application[], now = dayjs()): number {
  const days = new Set(
    apps.filter((a) => a.applied_at).map((a) => dayjs(a.applied_at).format('YYYY-MM-DD'))
  );
  let streak = 0;
  let cursor = now;
  while (days.has(cursor.format('YYYY-MM-DD'))) {
    streak++;
    cursor = cursor.subtract(1, 'day');
  }
  return streak;
}

export default function AppShell() {
  return (
    <PilotAttachmentProvider>
      <AppShellContent />
    </PilotAttachmentProvider>
  );
}

function AppShellContent() {
  const [view, setView] = useState<ViewMode>('dashboard');
  const [addOpen, setAddOpen] = useState(false);
  const [resumeUploadOpen, setResumeUploadOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [pilotDrawerOpen, setPilotDrawerOpen] = useState(false);
  const [aiSettingsOpen, setAISettingsOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);
  const [evidenceFocus, setEvidenceFocus] = useState<Exclude<EvidenceTarget, { kind: 'application' }> | null>(null);
  const [coachOfferId, setCoachOfferId] = useState<number | undefined>(undefined);
  const [chatStartRequest, setChatStartRequest] = useState<ChatStartRequest>();
  const [activePilotAttachmentKey, setActivePilotAttachmentKey] = useState<PilotAttachmentConversationKey>();
  const [pendingAttachmentDraftKey, setPendingAttachmentDraftKey] = useState<PilotAttachmentConversationKey>();
  const pilotAttachmentDraftKey = pendingAttachmentDraftKey;
  const pendingAttachmentDraftKeyRef = useRef<PilotAttachmentConversationKey>();
  const nextChatStartRequestKey = useRef(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [now, setNow] = useState(() => dayjs());
  const [pilotRailAvailable, setPilotRailAvailable] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia('(min-width: 1180px)').matches
  );
  const kanbanSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );
  const { addAttachment: addAttachmentToKey, createNewDraftWithAttachment } = usePilotAttachmentStore();

  const { data: applications = [], isLoading, isError: appsError } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications(),
  });
  const { data: events = [] } = useQuery({
    queryKey: ['events'],
    queryFn: () => listEvents(),
  });
  const { data: offers = [] } = useQuery({
    queryKey: ['offers'],
    queryFn: () => listOffers(),
  });
  const { data: practiceStats } = useQuery({
    queryKey: ['questions', 'stats'],
    queryFn: () => getPracticeStats(),
    retry: false,
  });

  // Backend serializes an empty []T slice as JSON `null` (Go encoding/json).
  // React Query's `= []` default only applies when data is `undefined`, so an
  // explicit null-coalesce is needed to keep downstream iterators safe.
  const apps = applications ?? [];
  const evs = events ?? [];
  const ofrs = offers ?? [];

  const qc = useQueryClient();
  const refreshWorkspaceData = () => {
    void qc.invalidateQueries({ queryKey: ['applications'] });
    void qc.invalidateQueries({ queryKey: ['events'] });
    void qc.invalidateQueries({ queryKey: ['offers'] });
    void qc.invalidateQueries({ queryKey: ['questions', 'stats'] });
    void qc.invalidateQueries({ queryKey: ['chat', 'conversations'] });
    void qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
  };

  const uploadResumeMut = useMutation({
    mutationFn: (f: File) => uploadResume(f),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，文本提取失败，请到简历库校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      qc.invalidateQueries({ queryKey: ONBOARDING_QUERY_KEY });
      setResumeUploadOpen(false);
    },
    onError: () => message.error('上传失败'),
  });

  useEffect(() => {
    const id = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1180px)');
    const sync = () => setPilotRailAvailable(media.matches);
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const pipelineActions = useMemo(
    () => derivePipelineInsights({ apps, events: evs, offers: ofrs, practiceStats, weeklyTarget: 6, now }),
    [apps, evs, ofrs, practiceStats, now]
  );
  const actions = useMemo(() => toLegacyActionItems(pipelineActions), [pipelineActions]);
  const streak = useMemo(() => computeStreak(apps, now), [apps, now]);

  const selectedApp = selected
    ? apps.find((a) => a.id === selected.id) ?? null
    : null;
  const coachedOffer = ofrs.find((offer) => offer.id === coachOfferId);
  const pageContext = useMemo(
    () =>
      buildPilotPageContext({
        view,
        selectedApplication: selectedApp ?? undefined,
        coachedOffer,
      }),
    [view, selectedApp, coachedOffer]
  );
  const moduleTabs = moduleTabsForView(view);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
  }, [selectedApp?.id, view]);

  useEffect(() => {
    if (selected && !apps.some((app) => app.id === selected.id)) {
      setSelected(null);
    }
  }, [apps, selected]);

  const shouldShowContextualPilot = view !== 'pilot';
  const contextualPilotPanelOpen = pilotRailAvailable ? pilotDrawerOpen : chatOpen;

  const openChat = (offerId?: number) => {
    setCoachOfferId(offerId);
    if (view === 'pilot') {
      setView('dashboard');
    }
    if (pilotRailAvailable) {
      setPilotDrawerOpen(true);
      return;
    }
    setChatOpen(true);
  };

  const attachToPilot = (attachment: PilotContextAttachment) => {
    const attachmentKey =
      activePilotAttachmentKey ?? pendingAttachmentDraftKeyRef.current ?? pendingAttachmentDraftKey;
    if (attachmentKey) {
      pendingAttachmentDraftKeyRef.current = attachmentKey;
      setPendingAttachmentDraftKey(attachmentKey);
      addAttachmentToKey(attachmentKey, attachment);
      return;
    }
    const key = createNewDraftWithAttachment(attachment);
    pendingAttachmentDraftKeyRef.current = key;
    setPendingAttachmentDraftKey(key);
  };

  const syncPilotAttachmentKey = (key?: PilotAttachmentConversationKey) => {
    setActivePilotAttachmentKey((currentKey) => retainPilotAttachmentKey(currentKey, key));
    if (key) {
      pendingAttachmentDraftKeyRef.current = undefined;
      setPendingAttachmentDraftKey(undefined);
    }
  };

  const handoffPilotAttachmentDraft = () => {
    const attachmentKey =
      activePilotAttachmentKey ?? pendingAttachmentDraftKeyRef.current ?? pendingAttachmentDraftKey;
    if (!attachmentKey) return;
    pendingAttachmentDraftKeyRef.current = attachmentKey;
    setPendingAttachmentDraftKey(attachmentKey);
  };

  const startApplicationChat = (application: Application) => {
    setCoachOfferId(undefined);
    setChatStartRequest({
      requestKey: ++nextChatStartRequestKey.current,
      context_type: 'application',
      context_ref: String(application.id),
      context_label: `${application.company_name} · ${application.position_name}`,
      mode: 'general',
    });
    if (view !== 'pilot') {
      if (pilotRailAvailable) setPilotDrawerOpen(true);
      else setChatOpen(true);
    }
  };

  const navigateToView = (nextView: ViewMode) => {
    setAISettingsOpen(false);
    setSelected(null);
    if (nextView === 'pilot') {
      setChatOpen(false);
      setPilotDrawerOpen(false);
      setCoachOfferId(undefined);
    }
    setView(nextView);
  };

  const openApplicationDetail = (app: Application) => {
    setAISettingsOpen(false);
    setSelected(app);
  };

  const clearEvidenceFocus = (target: EvidenceTarget) => {
    setEvidenceFocus((current) => (current === target ? null : current));
  };

  const openEvidence = (target: EvidenceTarget) => {
    setAISettingsOpen(false);
    if (view === 'pilot' && !pilotRailAvailable) {
      setChatOpen(true);
    }
    if (target.kind === 'application') {
      setEvidenceFocus(null);
      const app = apps.find((item) => item.id === target.id);
      if (app) {
        if (view === 'pilot') setView('board');
        openApplicationDetail(app);
      } else {
        message.warning('引用的记录已不存在');
      }
      return;
    }

    setSelected(null);
    setEvidenceFocus(target);
    if (target.kind === 'offer') {
      navigateToView('offers');
      return;
    }
    if (target.kind === 'resume') {
      navigateToView('resumes');
      return;
    }
    navigateToView('calendar');
  };

  const goDetailById = (appId: number) => {
    const app = apps.find((a) => a.id === appId);
    if (app) openApplicationDetail(app);
  };

  const runPipelineAction = (item: PipelineInsight) => {
    if (item.primaryAction.target === 'board' && item.appId) {
      goDetailById(item.appId);
      return;
    }

    navigateToView(item.primaryAction.target);
  };

  const calendarEvidenceFocus = evidenceFocus?.kind === 'event' ? evidenceFocus : undefined;
  const offerEvidenceFocus = evidenceFocus?.kind === 'offer' ? evidenceFocus : undefined;
  const resumeEvidenceFocus = evidenceFocus?.kind === 'resume' ? evidenceFocus : undefined;

  const workspaceContent = aiSettingsOpen ? (
    <AISettingsDrawer open onClose={() => setAISettingsOpen(false)} />
  ) : selectedApp ? (
    <ApplicationDetail
      application={selectedApp}
      open
      onClose={() => setSelected(null)}
      onAskPilot={startApplicationChat}
      onAttachToPilot={attachToPilot}
    />
  ) : (
    <>
      {moduleTabs.length > 1 && (
        <Tabs
          className="op-module-tabs"
          activeKey={view}
          onChange={(key) => navigateToView(key as ViewMode)}
          items={moduleTabs.map((item) => ({ key: item.view, label: item.label }))}
        />
      )}
      <Suspense
        fallback={
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin size="large" />
          </div>
        }
      >
        <div className="op-view-enter">
          {view === 'dashboard' && (
            <DashboardView
              onNavigate={navigateToView}
              onOpenDetailById={goDetailById}
              onAddApplication={() => setAddOpen(true)}
            />
          )}
          {view === 'board' && (
            <KanbanBoard applications={apps} onOpenDetail={openApplicationDetail} onAttachToPilot={attachToPilot} />
          )}
          {view === 'applications-list' && (
            <ApplicationListView
              applications={apps}
               events={evs}
               onOpenDetail={openApplicationDetail}
               onAskPilot={startApplicationChat}
               onAttachToPilot={attachToPilot}
            />
          )}
          {view === 'calendar' && (
            <CalendarView
              applications={apps}
              onOpenDetail={openApplicationDetail}
              focusEvent={calendarEvidenceFocus}
              onEvidenceFocusConsumed={calendarEvidenceFocus ? () => clearEvidenceFocus(calendarEvidenceFocus) : undefined}
            />
          )}
          {view === 'reminders' && (
            <RemindersView onNavigate={navigateToView} onOpenDetailById={goDetailById} />
          )}
          {view === 'offers' && (
            <OfferCenterView
              applications={apps}
              onCoach={(offer) => openChat(offer.id)}
              onAttachToPilot={attachToPilot}
              focusOfferId={offerEvidenceFocus?.id}
              onEvidenceFocusConsumed={offerEvidenceFocus ? () => clearEvidenceFocus(offerEvidenceFocus) : undefined}
            />
          )}
          {view === 'knowledge' && <KnowledgeLibraryView />}
          {view === 'questions' && <QuestionBankView />}
          {view === 'interview' && <InterviewV01View />}
          {view === 'resumes' && (
            <ResumeLibraryView
              onAttachToPilot={attachToPilot}
              focusResumeId={resumeEvidenceFocus?.id}
              onEvidenceFocusConsumed={resumeEvidenceFocus ? () => clearEvidenceFocus(resumeEvidenceFocus) : undefined}
            />
          )}
          {view === 'pilot' && (
            <div style={{ height: 'calc(100vh - 128px)', minHeight: 640 }}>
              <ChatPanel
                variant="page"
                open
                onClose={() => undefined}
                onOpenSettings={() => setAISettingsOpen(true)}
                startRequest={chatStartRequest}
                onDataChanged={refreshWorkspaceData}
                attachmentDraftKey={pilotAttachmentDraftKey}
                onAttachmentKeyChange={syncPilotAttachmentKey}
                onOpenEvidence={openEvidence}
              />
            </div>
          )}
          {view === 'settings' && <SettingsView onOpenAISettings={() => setAISettingsOpen(true)} />}
        </div>
      </Suspense>
    </>
  );

  return (
    <DndContext sensors={kanbanSensors}>
      <Layout
      className="op-app-shell"
      style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }}
      hasSider
    >
      <Sidebar
        view={view}
        onChange={navigateToView}
        reminderCount={actions.length}
      />
      <Layout className="op-app-main" style={{ background: 'var(--op-layout-bg)', minWidth: 0, width: '100%' }}>
        <TopBar
          streakDays={streak}
          onAdd={() => setAddOpen(true)}
          onSearch={() => setPaletteOpen(true)}
          onOpenSettings={() => setAISettingsOpen(true)}
        />
        <Content className="op-app-content" style={{ padding: '0 24px 24px' }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : appsError ? (
            <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
              加载失败，请稍后重试
            </div>
          ) : (
            <ViewErrorBoundary key={aiSettingsOpen ? 'ai-settings' : selectedApp ? `application-${selectedApp.id}` : view}>
              {workspaceContent}
            </ViewErrorBoundary>
          )}
        </Content>
      </Layout>
      {shouldShowContextualPilot && pilotRailAvailable && !pilotDrawerOpen && (
        <aside className="op-pilot-rail" aria-label="Pilot">
          <ChatPanel
            variant="rail"
            open
            pilotDropTarget
            onClose={() => setCoachOfferId(undefined)}
            offerId={coachOfferId}
            onOpenSettings={() => setAISettingsOpen(true)}
            onExpand={() => {
              handoffPilotAttachmentDraft();
              navigateToView('pilot');
            }}
            startRequest={chatStartRequest}
            onDataChanged={refreshWorkspaceData}
            pageContext={pageContext}
            attachmentDraftKey={pilotAttachmentDraftKey}
            onAttachmentKeyChange={syncPilotAttachmentKey}
            onOpenEvidence={openEvidence}
          />
        </aside>
      )}

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ResumeUploadModal
        open={resumeUploadOpen}
        uploading={uploadResumeMut.isPending}
        onSubmit={(f) => uploadResumeMut.mutate(f)}
        onClose={() => setResumeUploadOpen(false)}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        applications={apps}
        onNavigate={navigateToView}
        onOpenDetail={openApplicationDetail}
        onAddApplication={() => setAddOpen(true)}
        onOpenResume={() => navigateToView('resumes')}
        onUploadResume={() => setResumeUploadOpen(true)}
        onOpenChat={() => openChat(undefined)}
        onOpenSettings={() => setAISettingsOpen(true)}
        pipelineActions={pipelineActions}
        onRunPipelineAction={runPipelineAction}
      />
      {shouldShowContextualPilot && contextualPilotPanelOpen && (
        <ChatPanel
          open={contextualPilotPanelOpen}
          pilotDropTarget
          onClose={() => {
            setChatOpen(false);
            setPilotDrawerOpen(false);
            setCoachOfferId(undefined);
          }}
          offerId={coachOfferId}
          onOpenSettings={() => setAISettingsOpen(true)}
          startRequest={chatStartRequest}
          onDataChanged={refreshWorkspaceData}
          pageContext={pageContext}
          attachmentDraftKey={pilotAttachmentDraftKey}
          onAttachmentKeyChange={syncPilotAttachmentKey}
          onOpenEvidence={openEvidence}
        />
      )}
      </Layout>
    </DndContext>
  );
}
