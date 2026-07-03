import type { ActionItemSummary } from '@/lib/actionItems';
import type { Kpis } from '@/lib/insights';
import styles from '../dashboard.module.css';

interface Props {
  summary: ActionItemSummary;
  kpis: Kpis;
}

function rhythmCopy(summary: ActionItemSummary, kpis: Kpis): string {
  if (summary.p0 > 0) return '今天先处理紧急事项，再安排刷题和投递跟进。';
  if (summary.interviewSoon > 0) return '近期有面试安排，建议把题库练习和 JD 复盘放到前面。';
  if (summary.stale > 0) return '有投递进入停滞区间，建议集中做一次跟进。';
  if (kpis.weeklyDelta === 0) return '本周还没有新增投递，可以补充目标岗位或复盘简历。';
  return '当前节奏稳定，继续保持投递、复盘和练习的闭环。';
}

export default function WeeklyRhythm({ summary, kpis }: Props) {
  const pressure = Math.min(
    100,
    summary.p0 * 35 + summary.interviewSoon * 20 + summary.stale * 10 + Math.min(summary.dueQuestions, 10) * 3,
  );
  const calmScore = Math.max(8, 100 - pressure);

  return (
    <div className={styles.rhythmCard}>
      <div className={styles.cardTitle}>本周节奏</div>
      <div className={styles.rhythmTrack} aria-hidden="true">
        <div className={styles.rhythmBar} style={{ width: `${calmScore}%` }} />
      </div>
      <div className={styles.rhythmMeta}>
        <span className="op-tnum">稳定度 {calmScore}%</span>
        <span className="op-tnum">本周新增 {kpis.weeklyDelta}</span>
      </div>
      <p className={styles.rhythmText}>{rhythmCopy(summary, kpis)}</p>
    </div>
  );
}
