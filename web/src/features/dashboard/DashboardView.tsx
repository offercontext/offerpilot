import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Skeleton, Button } from 'antd';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import {
  computeKpis,
  computeFunnel,
  computeMomentum,
  deriveReminders,
} from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import KpiCards from './widgets/KpiCards';
import ConversionFunnel from './widgets/ConversionFunnel';
import MomentumChart from './widgets/MomentumChart';
import UpcomingSchedule from './widgets/UpcomingSchedule';
import RemindersSummary from './widgets/RemindersSummary';
import styles from './dashboard.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
  onAddApplication: () => void;
}

export default function DashboardView({ onNavigate, onAddApplication }: Props) {
  const appsQ = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const eventsQ = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const offersQ = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });

  const apps = appsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const offers = offersQ.data ?? [];

  const kpis = useMemo(() => computeKpis(apps), [apps]);
  const funnel = useMemo(() => computeFunnel(apps), [apps]);
  const momentum = useMemo(() => computeMomentum(apps), [apps]);
  const reminders = useMemo(() => deriveReminders(apps, events, offers, dayjs()), [apps, events, offers]);

  if (appsQ.isLoading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }

  if (apps.length === 0) {
    return (
      <div className={styles.grid}>
        <div className={styles.card} style={{ textAlign: 'center', padding: 48 }}>
          <div style={{ color: 'var(--op-muted)', marginBottom: 16 }}>还没有投递记录</div>
          <Button type="primary" onClick={onAddApplication}>
            添加第一个投递
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.grid}>
      <KpiCards kpis={kpis} />
      <div className={styles.row2}>
        <ConversionFunnel stages={funnel} />
        <RemindersSummary reminders={reminders} onSeeAll={() => onNavigate('reminders')} />
      </div>
      <div className={styles.row2b}>
        <MomentumChart buckets={momentum} />
        <UpcomingSchedule events={events} />
      </div>
    </div>
  );
}
