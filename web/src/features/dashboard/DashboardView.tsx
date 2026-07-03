import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Skeleton, Button } from 'antd';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { getPracticeStats } from '@/services/questions';
import { deriveActionItems, summarizeActionItems, type ActionItem } from '@/lib/actionItems';
import { computeKpis, computeFunnel, computeMomentum } from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import KpiCards from './widgets/KpiCards';
import ConversionFunnel from './widgets/ConversionFunnel';
import MomentumChart from './widgets/MomentumChart';
import UpcomingSchedule from './widgets/UpcomingSchedule';
import CommandCenter from './widgets/CommandCenter';
import styles from './dashboard.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
  onAddApplication: () => void;
}

export default function DashboardView({ onNavigate, onOpenDetailById, onAddApplication }: Props) {
  const [now, setNow] = useState(() => dayjs());

  useEffect(() => {
    const id = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const appsQ = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const eventsQ = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const offersQ = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });
  const practiceStatsQ = useQuery({
    queryKey: ['questions', 'stats'],
    queryFn: () => getPracticeStats(),
    retry: false,
  });

  const apps = appsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const offers = offersQ.data ?? [];

  const kpis = useMemo(() => computeKpis(apps, now), [apps, now]);
  const funnel = useMemo(() => computeFunnel(apps), [apps]);
  const momentum = useMemo(() => computeMomentum(apps, 4, now), [apps, now]);
  const actions = useMemo(
    () => deriveActionItems({ apps, events, offers, practiceStats: practiceStatsQ.data, now }),
    [apps, events, offers, practiceStatsQ.data, now],
  );
  const actionSummary = useMemo(() => summarizeActionItems(actions), [actions]);

  const handleAction = (item: ActionItem) => {
    if (item.target === 'board' && item.appId) {
      onOpenDetailById(item.appId);
      return;
    }
    onNavigate(item.target);
  };

  if (appsQ.isLoading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }

  if (apps.length === 0) {
    return (
      <div className={styles.grid}>
        <div className={styles.card} style={{ textAlign: 'center', padding: 48 }}>
          <div style={{ color: 'var(--op-ink)', fontSize: 18, fontWeight: 700, marginBottom: 8 }}>
            从第一条投递开始建立求职节奏
          </div>
          <div style={{ color: 'var(--op-muted)', marginBottom: 16 }}>
            添加投递后，OfferPilot 会自动生成跟进提醒、面试准备和 Offer 截止期行动。
          </div>
          <Button type="primary" onClick={onAddApplication}>
            添加第一个投递
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.grid}>
      <CommandCenter
        items={actions}
        summary={actionSummary}
        kpis={kpis}
        onAction={handleAction}
        onAddApplication={onAddApplication}
        onOpenQuestions={() => onNavigate('questions')}
        onSeeAll={() => onNavigate('reminders')}
      />
      <KpiCards kpis={kpis} />
      <div className={styles.row2b}>
        <ConversionFunnel stages={funnel} />
        <MomentumChart buckets={momentum} />
      </div>
      <div className={styles.row2b}>
        <UpcomingSchedule events={events} />
        <div className={styles.card}>
          <div className={styles.cardTitle}>行动说明</div>
          <div className={styles.empty}>
            今日行动由投递停滞、即将到来的面试、Offer 截止期和到期题目自动推导。
          </div>
        </div>
      </div>
    </div>
  );
}
