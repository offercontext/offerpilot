import { Component, lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Layout, Spin, message } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { uploadResume } from '@/services/resumes';
import type { Application } from '@/types/application';
import type { MockConfig } from '@/types/mock';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeMatchModal from '@/components/ResumeMatchModal';
import ResumeUploadModal from '@/components/ResumeUploadModal';
import ChatPanel from '@/components/ChatPanel';
import CommandPalette from './CommandPalette';
import {
  derivePipelineInsights,
  toLegacyActionItems,
  type PipelineInsight,
} from '@/lib/pipelineInsights';
import { getPracticeStats } from '@/services/questions';
import dayjs from 'dayjs';

const { Content } = Layout;

const KanbanBoard = lazy(() => import('@/components/KanbanBoard'));
const CalendarView = lazy(() => import('@/components/CalendarView'));
const ReviewManagementView = lazy(() => import('@/components/ReviewManagementView'));
const KnowledgeBaseView = lazy(() => import('@/components/KnowledgeBaseView'));
const QuestionBankView = lazy(() => import('@/components/QuestionBankView'));
const OfferCenterView = lazy(() => import('@/components/OfferCenterView'));
const DashboardView = lazy(() => import('@/features/dashboard/DashboardView'));
const RemindersView = lazy(() => import('@/features/reminders/RemindersView'));
const MockStudioView = lazy(() => import('@/components/MockStudio/MockStudioView'));
const ResumeLibraryView = lazy(() => import('@/components/ResumeLibraryView'));

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

export type ViewMode =
  | 'dashboard'
  | 'board'
  | 'calendar'
  | 'reminders'
  | 'reviews'
  | 'mock'
  | 'offers'
  | 'knowledge'
  | 'questions'
  | 'resumes';

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
  const [view, setView] = useState<ViewMode>('dashboard');
  const [addOpen, setAddOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [resumeUploadOpen, setResumeUploadOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);
  const [coachOfferId, setCoachOfferId] = useState<number | undefined>(undefined);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [mockPrefill, setMockPrefill] = useState<Partial<MockConfig> | null>(null);
  const [questionFocusId, setQuestionFocusId] = useState<number | null>(null);
  const [now, setNow] = useState(() => dayjs());

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
  const uploadResumeMut = useMutation({
    mutationFn: (f: File) => uploadResume(f),
    onSuccess: (res) => {
      message.success(res.parse_status === 'text-ready' ? '上传成功' : '已上传，文本提取失败，请到简历库校正');
      qc.invalidateQueries({ queryKey: ['resumes'] });
      setResumeUploadOpen(false);
    },
    onError: () => message.error('上传失败'),
  });

  useEffect(() => {
    const id = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(id);
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
    ? apps.find((a) => a.id === selected.id) ?? selected
    : null;

  const openChat = (offerId?: number) => {
    setCoachOfferId(offerId);
    setChatOpen(true);
  };

  const goDetailById = (appId: number) => {
    const app = apps.find((a) => a.id === appId);
    if (app) setSelected(app);
  };

  const runPipelineAction = (item: PipelineInsight) => {
    if (item.primaryAction.target === 'board' && item.appId) {
      goDetailById(item.appId);
      return;
    }

    setView(item.primaryAction.target);
  };

  return (
    <Layout
      className="op-app-shell"
      style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }}
      hasSider
    >
      <Sidebar
        view={view}
        onChange={setView}
        reminderCount={actions.length}
        onOpenChat={() => openChat(undefined)}
      />
      <Layout className="op-app-main" style={{ background: 'var(--op-layout-bg)', minWidth: 0, width: '100%' }}>
        <TopBar streakDays={streak} onAdd={() => setAddOpen(true)} onSearch={() => setPaletteOpen(true)} onOpenChat={() => openChat(undefined)} />
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
            <ViewErrorBoundary key={view}>
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
                      onNavigate={setView}
                      onOpenDetailById={goDetailById}
                      onAddApplication={() => setAddOpen(true)}
                    />
                  )}
                  {view === 'board' && (
                    <KanbanBoard applications={apps} onOpenDetail={(a) => setSelected(a)} />
                  )}
                  {view === 'calendar' && (
                    <CalendarView applications={apps} onOpenDetail={(a) => setSelected(a)} />
                  )}
                  {view === 'reminders' && (
                    <RemindersView onNavigate={setView} onOpenDetailById={goDetailById} />
                  )}
                  {view === 'reviews' && <ReviewManagementView applications={apps} />}
                  {view === 'offers' && (
                    <OfferCenterView applications={apps} onCoach={(offer) => openChat(offer.id)} />
                  )}
                  {view === 'knowledge' && <KnowledgeBaseView />}
                  {view === 'questions' && <QuestionBankView focusId={questionFocusId ?? undefined} />}
                  {view === 'mock' && (
                    <MockStudioView
                      prefill={mockPrefill}
                      onJumpQuestion={(id) => {
                        setQuestionFocusId(id);
                        setView('questions');
                      }}
                      onConsumePrefill={() => setMockPrefill(null)}
                    />
                  )}
                  {view === 'resumes' && <ResumeLibraryView />}
                </div>
              </Suspense>
            </ViewErrorBoundary>
          )}
        </Content>
      </Layout>

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ApplicationDetail
        application={selectedApp}
        open={!!selected}
        onClose={() => setSelected(null)}
        onMockInterview={(app) => {
          setSelected(null);
          setMockPrefill({
            application_id: app.id,
            role: app.position_name,
            company: app.company_name,
            round_type: 'technical',
            question_source: 'mixed',
          });
          setView('mock');
        }}
      />
      <ResumeMatchModal open={resumeOpen} onClose={() => setResumeOpen(false)} />
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
        onNavigate={setView}
        onOpenDetail={(app) => setSelected(app)}
        onAddApplication={() => setAddOpen(true)}
        onOpenResume={() => setResumeOpen(true)}
        onUploadResume={() => setResumeUploadOpen(true)}
        onOpenChat={() => openChat(undefined)}
        pipelineActions={pipelineActions}
        onRunPipelineAction={runPipelineAction}
      />
      <ChatPanel
        open={chatOpen}
        onClose={() => {
          setChatOpen(false);
          setCoachOfferId(undefined);
        }}
        offerId={coachOfferId}
      />
    </Layout>
  );
}
