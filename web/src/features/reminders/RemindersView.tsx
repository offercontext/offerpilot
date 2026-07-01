import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { deriveReminders, type Reminder, type ReminderSeverity } from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import styles from './reminders.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

const GROUPS: { key: ReminderSeverity; label: string }[] = [
  { key: 'red', label: '今日紧急' },
  { key: 'amber', label: '本周关注' },
  { key: 'green', label: '进行中' },
];

export default function RemindersView({ onNavigate, onOpenDetailById }: Props) {
  const { data: apps = [] } = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const { data: events = [] } = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const { data: offers = [] } = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });

  const reminders = useMemo(
    () => deriveReminders(apps, events, offers, dayjs()),
    [apps, events, offers]
  );

  const handleClick = (r: Reminder) => {
    if (r.target === 'board' && r.appId) {
      onOpenDetailById(r.appId);
    } else {
      onNavigate(r.target);
    }
  };

  if (reminders.length === 0) {
    return <div className={styles.empty}>暂无待办，保持节奏 ✦</div>;
  }

  return (
    <div className={styles.wrap}>
      {GROUPS.map(({ key, label }) => {
        const items = reminders.filter((r) => r.severity === key);
        if (items.length === 0) return null;
        return (
          <div key={key} className={styles.group}>
            <div className={styles.groupTitle}>
              {label}（{items.length}）
            </div>
            {items.map((r, i) => (
              <div
                key={r.id}
                className={styles.item}
                style={{ animationDelay: `${i * 40}ms` }}
                onClick={() => handleClick(r)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && handleClick(r)}
              >
                <span className={`${styles.dot} ${styles[r.severity]}`} />
                <div className={styles.body}>
                  <div className={styles.title}>{r.title}</div>
                  <div className={styles.detail}>{r.detail}</div>
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
