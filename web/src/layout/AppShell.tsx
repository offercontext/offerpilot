import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout, Spin } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import type { Application } from '@/types/application';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import KanbanBoard from '@/components/KanbanBoard';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeMatchModal from '@/components/ResumeMatchModal';
import CalendarView from '@/components/CalendarView';
import ChatPanel from '@/components/ChatPanel';
import ReviewManagementView from '@/components/ReviewManagementView';
import KnowledgeBaseView from '@/components/KnowledgeBaseView';
import OfferCenterView from '@/components/OfferCenterView';
import DashboardView from '@/features/dashboard/DashboardView';
import RemindersView from '@/features/reminders/RemindersView';
import CommandPalette from './CommandPalette';
import { deriveReminders, reminderBadgeCount } from '@/lib/insights';
import dayjs from 'dayjs';

const { Content } = Layout;

export type ViewMode =
  | 'dashboard'
  | 'board'
  | 'calendar'
  | 'reminders'
  | 'reviews'
  | 'offers'
  | 'knowledge';

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
  const [chatOpen, setChatOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);
  const [coachOfferId, setCoachOfferId] = useState<number | undefined>(undefined);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const { data: applications = [], isLoading } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications(),
  });
  const { data: events = [] } = useQuery({
    queryKey: ['events'],
    queryFn: () => listEvents(),
  });

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

  const reminders = useMemo(
    () => deriveReminders(applications, events, [], dayjs()),
    [applications, events]
  );
  const streak = useMemo(() => computeStreak(applications), [applications]);

  const selectedApp = selected
    ? applications.find((a) => a.id === selected.id) ?? selected
    : null;

  const openChat = (offerId?: number) => {
    setCoachOfferId(offerId);
    setChatOpen(true);
  };

  const goDetailById = (appId: number) => {
    const app = applications.find((a) => a.id === appId);
    if (app) setSelected(app);
  };

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }} hasSider>
      <Sidebar
        view={view}
        onChange={setView}
        reminderCount={reminderBadgeCount(reminders)}
        onOpenChat={() => openChat(undefined)}
      />
      <Layout style={{ background: 'var(--op-layout-bg)' }}>
        <TopBar streakDays={streak} onAdd={() => setAddOpen(true)} onSearch={() => setPaletteOpen(true)} />
        <Content style={{ padding: '0 24px 24px' }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : (
            <div className="op-view-enter" key={view}>
              {view === 'dashboard' && (
                <DashboardView onNavigate={setView} onOpenDetailById={goDetailById} />
              )}
              {view === 'board' && (
                <KanbanBoard applications={applications} onOpenDetail={(a) => setSelected(a)} />
              )}
              {view === 'calendar' && (
                <CalendarView applications={applications} onOpenDetail={(a) => setSelected(a)} />
              )}
              {view === 'reminders' && (
                <RemindersView onNavigate={setView} onOpenDetailById={goDetailById} />
              )}
              {view === 'reviews' && <ReviewManagementView applications={applications} />}
              {view === 'offers' && (
                <OfferCenterView applications={applications} onCoach={(offer) => openChat(offer.id)} />
              )}
              {view === 'knowledge' && <KnowledgeBaseView />}
            </div>
          )}
        </Content>
      </Layout>

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ApplicationDetail application={selectedApp} open={!!selected} onClose={() => setSelected(null)} />
      <ResumeMatchModal open={resumeOpen} onClose={() => setResumeOpen(false)} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        applications={applications}
        onNavigate={setView}
        onOpenDetail={(app) => setSelected(app)}
        onAddApplication={() => setAddOpen(true)}
        onOpenResume={() => setResumeOpen(true)}
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
