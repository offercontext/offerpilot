import {
  CalendarOutlined,
  CheckCircleOutlined,
  FileDoneOutlined,
  FlagOutlined,
  ReadOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import type { ReactNode } from 'react';
import type { MissionMetric, MissionMetricKind, MissionMetricState } from '@/lib/missionControl';
import type { ViewMode } from '@/layout/AppShell';
import styles from '../dashboard.module.css';

interface Props {
  metrics: MissionMetric[];
  onNavigate: (view: ViewMode) => void;
}

const ICONS: Record<MissionMetricKind, ReactNode> = {
  applications: <FlagOutlined />,
  followups: <CheckCircleOutlined />,
  interviews: <CalendarOutlined />,
  practice: <ReadOutlined />,
  materials: <FileDoneOutlined />,
  offers: <TrophyOutlined />,
};

const STATE_LABELS: Record<MissionMetricState, string> = {
  on_track: '正常',
  watch: '关注',
  behind: '落后',
  blocked: '阻塞',
};

function formatValue(metric: MissionMetric): string {
  if (metric.target == null || metric.target === 0) return `${metric.current}`;
  return `${metric.current}/${metric.target}`;
}

export default function WeeklyMissionPanel({ metrics, onNavigate }: Props) {
  return (
    <section className={styles.weeklyMissionPanel} aria-label="本周目标">
      {metrics.map((metric) => (
        <button
          key={metric.kind}
          type="button"
          className={`${styles.missionMetric} ${styles[`metric-${metric.state}`]}`}
          onClick={() => onNavigate(metric.targetView)}
        >
          <span className={styles.metricIcon} aria-hidden="true">
            {ICONS[metric.kind]}
          </span>
          <span className={styles.metricBody}>
            <span className={styles.metricLabel}>{metric.label}</span>
            <span className={`${styles.metricValue} op-tnum`}>{formatValue(metric)}</span>
            <span className={styles.metricReason}>{metric.reason}</span>
          </span>
          <span className={styles.metricState}>{STATE_LABELS[metric.state]}</span>
        </button>
      ))}
    </section>
  );
}
