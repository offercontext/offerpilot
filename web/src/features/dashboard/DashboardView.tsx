import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Skeleton, Button } from 'antd';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { getApplicationMaterialKit } from '@/services/materialKits';
import { getPracticeStats } from '@/services/questions';
import {
  derivePipelineInsights,
  summarizePipelineHealth,
  type ActionCommand,
  type PipelineInsight,
} from '@/lib/pipelineInsights';
import { deriveMissionControl } from '@/lib/missionControl';
import { computeKpis, computeFunnel, computeMomentum } from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import type { MaterialKitViewModel } from '@/types/materialKit';
import ActionDetailDrawer from '@/features/pipeline/ActionDetailDrawer';
import KpiCards from './widgets/KpiCards';
import ConversionFunnel from './widgets/ConversionFunnel';
import MomentumChart from './widgets/MomentumChart';
import UpcomingSchedule from './widgets/UpcomingSchedule';
import MissionHeader from './widgets/MissionHeader';
import WeeklyMissionPanel from './widgets/WeeklyMissionPanel';
import TodayActionPlan from './widgets/TodayActionPlan';
import ApplicationReadinessStrip from './widgets/ApplicationReadinessStrip';
import FocusWorkspace from './widgets/FocusWorkspace';
import styles from './dashboard.module.css';

type DetailAction = ActionCommand & { id?: string };
type DetailInsight = PipelineInsight & {
  primaryAction: DetailAction;
  secondaryActions?: DetailAction[];
};

function getActionId(insight: PipelineInsight, action: DetailAction, kind: 'primary' | 'secondary') {
  return action.id ?? `${insight.id}:${kind}:${action.label}`;
}

function findInsightAction(item: PipelineInsight, actionId: string): DetailAction {
  const detail = item as DetailInsight;
  const actions = [detail.primaryAction, ...(detail.secondaryActions ?? [])];
  return (
    actions.find((action, index) => getActionId(item, action, index === 0 ? 'primary' : 'secondary') === actionId) ??
    detail.primaryAction
  );
}

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
  onAddApplication: () => void;
}

export default function DashboardView({ onNavigate, onOpenDetailById, onAddApplication }: Props) {
  const [now, setNow] = useState(() => dayjs());
  const [selectedInsightId, setSelectedInsightId] = useState<string | null>(null);
  const [focusApplicationId, setFocusApplicationId] = useState<number | undefined>(undefined);

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

  const activeApplications = useMemo(
    () => apps.filter((app) => ['pending', 'applied', 'written_test', 'interview', 'offer'].includes(app.status)),
    [apps],
  );
  const activeApplicationIds = useMemo(() => activeApplications.slice(0, 8).map((app) => app.id), [activeApplications]);

  const materialKitsQ = useQuery({
    queryKey: ['mission-control', 'material-kits', activeApplicationIds],
    queryFn: async () => {
      const kits = await Promise.all(activeApplicationIds.map((id) => getApplicationMaterialKit(id)));
      return kits.filter((kit): kit is MaterialKitViewModel => Boolean(kit));
    },
    enabled: activeApplicationIds.length > 0,
    retry: false,
  });
  const hasPartialMaterialKitCoverage = activeApplications.length > activeApplicationIds.length;
  const missionMaterialKits = hasPartialMaterialKitCoverage ? undefined : materialKitsQ.data;

  const kpis = useMemo(() => computeKpis(apps, now), [apps, now]);
  const funnel = useMemo(() => computeFunnel(apps), [apps]);
  const momentum = useMemo(() => computeMomentum(apps, 4, now), [apps, now]);
  const insights = useMemo(
    () => derivePipelineInsights({ apps, events, offers, practiceStats: practiceStatsQ.data, weeklyTarget: 6, now }),
    [apps, events, offers, practiceStatsQ.data, now],
  );
  const health = useMemo(() => summarizePipelineHealth(apps, insights, 6, now), [apps, insights, now]);
  const mission = useMemo(
    () =>
      deriveMissionControl({
        apps,
        events,
        offers,
        materialKits: missionMaterialKits,
        practiceStats: practiceStatsQ.data,
        insights,
        healthLabel: health.label,
        weeklyTarget: 6,
        now,
      }),
    [apps, events, offers, missionMaterialKits, practiceStatsQ.data, insights, health.label, now],
  );

  const effectiveFocusApplicationId = focusApplicationId ?? mission.focusApplicationId;
  const focusApplication = effectiveFocusApplicationId
    ? apps.find((app) => app.id === effectiveFocusApplicationId)
    : undefined;
  const focusReadiness = effectiveFocusApplicationId
    ? mission.readiness.find((item) => item.applicationId === effectiveFocusApplicationId)
    : undefined;
  const nextMissionAction = mission.actions[0];
  const selectedInsight = useMemo(
    () => insights.find((item) => item.id === selectedInsightId) ?? null,
    [insights, selectedInsightId],
  );

  useEffect(() => {
    if (selectedInsightId && !selectedInsight) {
      setSelectedInsightId(null);
    }
  }, [selectedInsight, selectedInsightId]);

  useEffect(() => {
    if (focusApplicationId && !mission.readiness.some((item) => item.applicationId === focusApplicationId)) {
      setFocusApplicationId(undefined);
    }
  }, [focusApplicationId, mission.readiness]);

  const handleAction = (item: PipelineInsight) => {
    setSelectedInsightId(item.id);
  };

  const runInsightAction = (item: PipelineInsight, actionId: string) => {
    const action = findInsightAction(item, actionId);
    const appId = action.appId ?? item.appId;

    setSelectedInsightId(null);
    if (action.target === 'board' && appId) {
      onOpenDetailById(appId);
      return;
    }
    onNavigate(action.target);
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
    <>
      <div className={styles.grid}>
        <MissionHeader
          summary={mission}
          nextAction={nextMissionAction}
          onRunAction={handleAction}
          onAddApplication={onAddApplication}
        />
        <WeeklyMissionPanel metrics={mission.metrics} onNavigate={onNavigate} />
        <div className={styles.missionWorkspaceGrid}>
          <TodayActionPlan
            groups={mission.actionGroups}
            onAction={handleAction}
            onSeeAll={() => onNavigate('reminders')}
          />
          <FocusWorkspace
            application={focusApplication}
            readiness={focusReadiness}
            onOpenDetail={onOpenDetailById}
            onNavigate={onNavigate}
          />
        </div>
        <ApplicationReadinessStrip
          items={mission.readiness}
          focusApplicationId={effectiveFocusApplicationId}
          onFocus={setFocusApplicationId}
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
      <ActionDetailDrawer
        insight={selectedInsight}
        open={!!selectedInsight}
        onClose={() => setSelectedInsightId(null)}
        onRunAction={runInsightAction}
      />
    </>
  );
}
