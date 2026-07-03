import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Input, Select } from 'antd';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { getPracticeStats } from '@/services/questions';
import {
  derivePipelineInsights,
  type ActionCommand,
  type PipelineInsight,
  type PipelineInsightKind,
  type PipelinePriority,
} from '@/lib/pipelineInsights';
import ActionDetailDrawer from '@/features/pipeline/ActionDetailDrawer';
import type { ViewMode } from '@/layout/AppShell';
import styles from './reminders.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

const GROUPS: { key: PipelinePriority; label: string }[] = [
  { key: 'p0', label: 'Today urgent' },
  { key: 'p1', label: 'This week focus' },
  { key: 'p2', label: 'Follow-up queue' },
];

function defineKindFilterOptions<const Options extends readonly { value: PipelineInsightKind | 'all'; label: string }[]>(
  options: Options &
    (Exclude<PipelineInsightKind, Exclude<Options[number]['value'], 'all'>> extends never ? unknown : never),
) {
  return options;
}

const KIND_FILTER_OPTIONS = defineKindFilterOptions([
  { value: 'all', label: 'All actions' },
  { value: 'offer_deadline', label: 'Offer deadline' },
  { value: 'interview_soon', label: 'Interview soon' },
  { value: 'stale_application', label: 'Stale application' },
  { value: 'no_next_event', label: 'No next event' },
  { value: 'material_kit_incomplete', label: 'Material kit incomplete' },
  { value: 'question_due', label: 'Question due' },
  { value: 'pipeline_bottleneck', label: 'Pipeline bottlenecks' },
  { value: 'weekly_goal_gap', label: 'Weekly goal gap' },
] satisfies { value: PipelineInsightKind | 'all'; label: string }[]);

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

export default function RemindersView({ onNavigate, onOpenDetailById }: Props) {
  const [now, setNow] = useState(() => dayjs());
  const [selectedInsightId, setSelectedInsightId] = useState<string | null>(null);
  const [kind, setKind] = useState<PipelineInsightKind | 'all'>('all');
  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    const id = window.setInterval(() => setNow(dayjs()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const { data: rawApps = [] } = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const { data: rawEvents = [] } = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const { data: rawOffers = [] } = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });
  const practiceStatsQ = useQuery({
    queryKey: ['questions', 'stats'],
    queryFn: () => getPracticeStats(),
    retry: false,
  });

  // Backend serializes empty []T as JSON `null`; coalesce to [] for safe iteration.
  const apps = rawApps ?? [];
  const events = rawEvents ?? [];
  const offers = rawOffers ?? [];

  const insights = useMemo(
    () => derivePipelineInsights({ apps, events, offers, practiceStats: practiceStatsQ.data, weeklyTarget: 6, now }),
    [apps, events, offers, practiceStatsQ.data, now],
  );

  const filteredInsights = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();
    return insights.filter((item) => {
      if (kind !== 'all' && item.kind !== kind) return false;
      if (!normalizedKeyword) return true;

      const searchable = [item.title, item.reason, ...(item.evidence ?? [])].join(' ').toLowerCase();
      return searchable.includes(normalizedKeyword);
    });
  }, [insights, keyword, kind]);

  const selectedInsight = useMemo(
    () => insights.find((item) => item.id === selectedInsightId) ?? null,
    [insights, selectedInsightId],
  );

  useEffect(() => {
    if (selectedInsightId && !selectedInsight) {
      setSelectedInsightId(null);
    }
  }, [selectedInsight, selectedInsightId]);

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

  return (
    <>
      <div className={styles.wrap}>
        <div className={styles.toolbar}>
          <Input.Search
            allowClear
            placeholder="Search pipeline actions"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onSearch={setKeyword}
          />
          <Select value={kind} options={KIND_FILTER_OPTIONS} onChange={setKind} aria-label="Filter action kind" />
        </div>

        {filteredInsights.length === 0 ? (
          <div className={styles.empty}>
            No matching pipeline actions. Add an application, practice due questions, or write a retrospective to keep
            momentum.
          </div>
        ) : (
          GROUPS.map(({ key, label }) => {
            const items = filteredInsights.filter((item) => item.priority === key);
            if (items.length === 0) return null;
            return (
              <div key={key} className={styles.group}>
                <div className={styles.groupTitle}>
                  {label} ({items.length})
                </div>
                {items.map((item, i) => (
                  <button
                    key={item.id}
                    type="button"
                    className={styles.item}
                    style={{ animationDelay: `${i * 40}ms` }}
                    onClick={() => setSelectedInsightId(item.id)}
                  >
                    <span className={`${styles.dot} ${styles[item.priority]}`} aria-hidden="true" />
                    <span className={styles.body}>
                      <span className={styles.title}>{item.title}</span>
                      <span className={styles.detail}>{item.reason}</span>
                    </span>
                    <span className={styles.primaryAction}>{item.primaryAction.label}</span>
                  </button>
                ))}
              </div>
            );
          })
        )}
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
