import type { ToolStep, TurnPresentation } from './model';
import ProcessTimeline from './ProcessTimeline';
import styles from './ChatPanel.module.css';

interface Props {
  title: string;
  steps: ToolStep[];
  presentation?: TurnPresentation;
  disabled: boolean;
  onAction: (action: string) => void;
}

function completionStatus(steps: ToolStep[], presentation?: TurnPresentation): string {
  if (steps.length) return `已完成 ${steps.length} 步`;
  if (presentation) return '已完成建议整理';
  return '等待处理';
}

export default function PilotTaskCard({ title, steps, presentation, disabled, onAction }: Props) {
  const status = completionStatus(steps, presentation);

  return (
    <article className={styles.taskCard} aria-label={`本轮任务：${title}`}>
      <header className={styles.taskHead}>
        <div>
          <span className={styles.taskLabel}>本轮任务</span>
          <h3 className={styles.taskTitle}>{title}</h3>
        </div>
        <span className={styles.taskStatus}>{status}</span>
      </header>

      {steps.length ? <ProcessTimeline steps={steps} summary={status} embedded /> : null}

      {presentation ? (
        <section className={styles.taskConclusion} aria-label="结论">
          <h4>结论</h4>
          <p>{presentation.conclusion}</p>
        </section>
      ) : null}

      {presentation?.actions.length ? (
        <section className={styles.taskActions} aria-label="下一步">
          <h4>下一步</h4>
          <div>
            {presentation.actions.map((action) => (
              <button
                key={action}
                type="button"
                aria-label={`继续：${action}`}
                disabled={disabled}
                onClick={() => onAction(action)}
              >
                {action}
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </article>
  );
}
