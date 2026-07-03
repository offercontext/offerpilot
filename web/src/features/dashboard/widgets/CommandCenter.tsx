import { Button } from 'antd';
import type { ActionItem, ActionItemSummary } from '@/lib/actionItems';
import type { Kpis } from '@/lib/insights';
import ActionQueue from './ActionQueue';
import ActionSummary from './ActionSummary';
import WeeklyRhythm from './WeeklyRhythm';
import styles from '../dashboard.module.css';

interface Props {
  items: ActionItem[];
  summary: ActionItemSummary;
  kpis: Kpis;
  onAction: (item: ActionItem) => void;
  onAddApplication: () => void;
  onOpenQuestions: () => void;
  onSeeAll: () => void;
}

export default function CommandCenter({
  items,
  summary,
  kpis,
  onAction,
  onAddApplication,
  onOpenQuestions,
  onSeeAll,
}: Props) {
  return (
    <section className={styles.commandCenter} aria-labelledby="command-center-title">
      <div className={styles.commandMain}>
        <div className={styles.commandHeader}>
          <div>
            <div className={styles.commandEyebrow}>Today Command Center</div>
            <h2 id="command-center-title" className={styles.commandTitle}>
              今天最值得推进的 {items.length} 件事
            </h2>
            <p className={styles.commandSubtitle}>按紧急度、截止期、面试时间和停滞天数自动排序。</p>
          </div>
          <Button onClick={onSeeAll}>查看全部提醒</Button>
        </div>
        <ActionSummary summary={summary} />
        <ActionQueue
          items={items}
          onAction={onAction}
          onAddApplication={onAddApplication}
          onOpenQuestions={onOpenQuestions}
          onSeeAll={onSeeAll}
        />
      </div>
      <aside className={styles.commandAside}>
        <WeeklyRhythm summary={summary} kpis={kpis} />
        <div className={styles.quickCard}>
          <div className={styles.cardTitle}>快速入口</div>
          <div className={styles.quickGrid}>
            <Button onClick={onAddApplication}>添加投递</Button>
            <Button onClick={onOpenQuestions}>打开题库</Button>
          </div>
        </div>
      </aside>
    </section>
  );
}
