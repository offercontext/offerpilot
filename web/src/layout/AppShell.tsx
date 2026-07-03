import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout, Spin, message } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { uploadResume } from '@/services/resumes';
import type { Application } from '@/types/application';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import KanbanBoard from '@/components/KanbanBoard';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeMatchModal from '@/components/ResumeMatchModal';
import ResumeLibraryView from '@/components/ResumeLibraryView';
import ResumeUploadModal from '@/components/ResumeUploadModal';
import CalendarView from '@/components/CalendarView';
import ChatPanel from '@/components/ChatPanel';
import ReviewManagementView from '@/components/ReviewManagementView';
import KnowledgeBaseView from '@/components/KnowledgeBaseView';
import QuestionBankView from '@/components/QuestionBankView';
import OfferCenterView from '@/components/OfferCenterView';
import DashboardView from '@/features/dashboard/DashboardView';
import RemindersView from '@/features/reminders/RemindersView';
import CommandPalette from './CommandPalette';
import { deriveActionItems } from '@/lib/actionItems';
import { getPracticeStats } from '@/services/questions';
import dayjs from 'dayjs';

const { Content } = Layout;

export type ViewMode =
  | 'dashboard'
  | 'board'
  | 'calendar'
  | 'reminders'
  | 'reviews'
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

  const actions = useMemo(
    () => deriveActionItems({ apps, events: evs, offers: ofrs, practiceStats, now }),
    [apps, evs, ofrs, practiceStats, now]
  );
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

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }} hasSider>
      <Sidebar
        view={view}
        onChange={setView}
        reminderCount={actions.length}
        onOpenChat={() => openChat(undefined)}
      />
      <Layout style={{ background: 'var(--op-layout-bg)' }}>
        <TopBar streakDays={streak} onAdd={() => setAddOpen(true)} onSearch={() => setPaletteOpen(true)} onOpenChat={() => openChat(undefined)} />
        <Content style={{ padding: '0 24px 24px' }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : appsError ? (
            <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
              加载失败，请稍后重试
            </div>
          ) : (
            <div className="op-view-enter" key={view}>
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
              {view === 'questions' && <QuestionBankView />}
              {view === 'resumes' && <ResumeLibraryView />}
            </div>
          )}
        </Content>
      </Layout>

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ApplicationDetail application={selectedApp} open={!!selected} onClose={() => setSelected(null)} />
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
