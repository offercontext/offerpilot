import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { getPracticeStats } from '@/services/questions';
import { deriveActionItems, type ActionItem, type ActionItemPriority } from '@/lib/actionItems';
import type { ViewMode } from '@/layout/AppShell';
import styles from './reminders.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

const GROUPS: { key: ActionItemPriority; label: string }[] = [
  { key: 'p0', label: '今日紧急' },
  { key: 'p1', label: '本周重点' },
  { key: 'p2', label: '后续推进' },
];

export default function RemindersView({ onNavigate, onOpenDetailById }: Props) {
  const [now, setNow] = useState(() => dayjs());

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

  const actions = useMemo(
    () => deriveActionItems({ apps, events, offers, practiceStats: practiceStatsQ.data, now }),
    [apps, events, offers, practiceStatsQ.data, now],
  );

  const handleClick = (item: ActionItem) => {
    if (item.kind === 'question_due') {
      onNavigate('questions');
      return;
    }

    if (item.target === 'board' && item.appId) {
      onOpenDetailById(item.appId);
      return;
    }

    onNavigate(item.target);
  };

  if (actions.length === 0) {
    return <div className={styles.empty}>暂无待办，保持节奏 ✦</div>;
  }

  return (
    <div className={styles.wrap}>
      {GROUPS.map(({ key, label }) => {
        const items = actions.filter((item) => item.priority === key);
        if (items.length === 0) return null;
        return (
          <div key={key} className={styles.group}>
            <div className={styles.groupTitle}>
              {label}（{items.length}）
            </div>
            {items.map((item, i) => (
              <button
                key={item.id}
                type="button"
                className={styles.item}
                style={{ animationDelay: `${i * 40}ms` }}
                onClick={() => handleClick(item)}
              >
                <span className={`${styles.dot} ${styles[item.priority]}`} aria-hidden="true" />
                <span className={styles.body}>
                  <span className={styles.title}>{item.title}</span>
                  <span className={styles.detail}>{item.detail}</span>
                </span>
                <span className={styles.primaryAction}>{item.primaryActionLabel}</span>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}
