import type { EvidenceTarget, ToolStep, TurnPresentation } from './model';
import ProcessTimeline from './ProcessTimeline';
import styles from './ChatPanel.module.css';
import { SourceStateTag, type SourceState } from '../ui/SourceStateTag';

interface Props {
  title: string;
  steps: ToolStep[];
  presentation?: TurnPresentation;
  disabled: boolean;
  onAction: (action: string) => void;
  onOpenEvidence?: (target: EvidenceTarget) => void;
  sourceState?: SourceState;
  resultUnknown?: boolean;
  operationState?: 'idle' | 'pending' | 'confirming';
}

function completionStatus(steps: ToolStep[], presentation?: TurnPresentation): string {
  if (steps.length) return `已完成 ${steps.length} 步`;
  if (presentation) return '已完成建议整理';
  return '等待处理';
}

function normalizeActions(actions: string[]): string[] {
  const uniqueActions: string[] = [];
  const seen = new Set<string>();

  for (const action of actions) {
    const normalized = action.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    uniqueActions.push(normalized);
  }

  return uniqueActions;
}

export default function PilotTaskCard({
  title,
  steps,
  presentation,
  disabled,
  onAction,
  onOpenEvidence,
  sourceState,
  resultUnknown = false,
  operationState = 'idle',
}: Props) {
  const status = completionStatus(steps, presentation);
  const actions = normalizeActions(presentation?.actions ?? []);
  const operationLabels = [
    resultUnknown ? '结果待确认' : null,
    operationState === 'confirming' ? '等待人工确认' : null,
    !resultUnknown && operationState === 'pending' ? '操作处理中' : null,
  ].filter((label): label is string => Boolean(label));

  return (
    <article className={styles.taskCard} aria-label={`本轮任务：${title}`}>
      <header className={styles.taskHead}>
        <div>
          <span className={styles.taskLabel}>本轮任务</span>
          <h3 className={styles.taskTitle}>{title}</h3>
        </div>
        <span className={styles.taskStatus}>{status}</span>
      </header>

      {sourceState ? <SourceStateTag state={sourceState} detail="Pilot 本轮操作来源" /> : null}
      {operationLabels.length > 0 ? (
        <p role="status">{operationLabels.join('，')}{resultUnknown ? '，请使用原尝试重试。' : ''}</p>
      ) : null}

      {steps.length ? <ProcessTimeline steps={steps} summary={status} embedded onOpenEvidence={onOpenEvidence} /> : null}

      {presentation ? (
        <section className={styles.taskConclusion} aria-label="结论">
          <h4>结论</h4>
          <p>{presentation.conclusion}</p>
        </section>
      ) : null}

      {actions.length ? (
        <section className={styles.taskActions} aria-label="下一步">
          <h4>下一步</h4>
          <div>
            {actions.map((action) => (
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
