import { Button } from 'antd';
import type { Kpis } from '@/lib/insights';
import type { PipelineHealth, PipelineInsight } from '@/lib/pipelineInsights';
import ActionQueue from './ActionQueue';
import WeeklyRhythm from './WeeklyRhythm';
import styles from '../dashboard.module.css';

interface Props {
  items: PipelineInsight[];
  health: PipelineHealth;
  kpis: Kpis;
  onAction: (item: PipelineInsight) => void;
  onAddApplication: () => void;
  onOpenQuestions: () => void;
  onSeeAll: () => void;
}

export default function CommandCenter({
  items,
  health,
  onAction,
  onAddApplication,
  onOpenQuestions,
  onSeeAll,
}: Props) {
  const actionLabel = items.length === 1 ? 'action' : 'actions';

  return (
    <section className={styles.commandCenter} aria-labelledby="command-center-title">
      <div className={styles.commandMain}>
        <div className={styles.commandHeader}>
          <div>
            <div className={styles.commandEyebrow}>Pipeline Intelligence</div>
            <h2 id="command-center-title" className={styles.commandTitle}>
              Today has {items.length} recommended {actionLabel}
            </h2>
            <p className={styles.commandSubtitle}>
              Ranked by deadline, pipeline risk, and preparation leverage. Each recommendation explains why it
              matters.
            </p>
          </div>
          <Button onClick={onSeeAll}>查看全部提醒</Button>
        </div>
        <div className={styles.pipelineHealthStrip}>
          <div>
            <div className={styles.healthLabel}>Health score</div>
            <div className={`${styles.healthText} op-tnum`}>{health.score}</div>
          </div>
          <div>
            <div className={styles.healthLabel}>State</div>
            <div className={styles.healthText}>{health.label}</div>
          </div>
          <div>
            <div className={styles.healthLabel}>Bottleneck</div>
            <div className={styles.healthText}>{health.bottleneck}</div>
          </div>
        </div>
        <ActionQueue
          items={items}
          onAction={onAction}
          onAddApplication={onAddApplication}
          onOpenQuestions={onOpenQuestions}
          onSeeAll={onSeeAll}
        />
      </div>
      <aside className={styles.commandAside}>
        <WeeklyRhythm health={health} />
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
