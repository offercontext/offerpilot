import { createElement } from 'react';
import { Alert, Button } from 'antd';
import type { PendingAction } from '@/types/chat';
import type { EvidenceItem } from './model';
import { toolMeta } from './capabilities';
import EvidenceList from './EvidenceList';
import styles from './ChatPanel.module.css';

interface Props {
  action: PendingAction;
  loading: boolean;
  evidence: EvidenceItem[];
  onConfirm: () => void;
  onCancel: () => void;
}

/** Best-effort "从 X 改为 Y" extraction for a before→after chip diff. */
function parseDiff(human: string): { was: string; now: string } | null {
  const m = human.match(
    /从\s*[「『"']?([^」』"'，,]+?)[」』"']?\s*(?:改为|变为|更新为|调整为|设为)\s*[「『"']?([^」』"'。.\s]+)/,
  );
  if (!m) return null;
  return { was: m[1].trim(), now: m[2].trim() };
}

function actionTarget(action: PendingAction): string | null {
  const id = action.args?.id;
  if (typeof id === 'number' || typeof id === 'string') return `Record #${id}`;
  const company = action.args?.company_name;
  const role = action.args?.position_name;
  if (typeof company === 'string' && typeof role === 'string') return `${company} · ${role}`;
  if (typeof company === 'string') return company;
  return null;
}

function proposedValue(action: PendingAction): string | null {
  const status = action.args?.status;
  if (typeof status === 'string' && status.trim()) return `Status -> ${status}`;
  const title = action.args?.title;
  if (typeof title === 'string' && title.trim()) return `Title -> ${title}`;
  return null;
}

export default function ProposalCard({ action, loading, evidence, onConfirm, onCancel }: Props) {
  const meta = toolMeta(action.tool_name);
  const diff = parseDiff(action.human);
  const target = actionTarget(action);
  const proposed = proposedValue(action);
  const thinEvidence = evidence.length === 0;

  return (
    <div className={styles.proposal} role="group" aria-label="AI 修改提议">
      <div className={styles.prHead}>
        <span className={styles.prIcon} aria-hidden="true">
          {createElement(meta.icon)}
        </span>
        AI 想执行一个修改操作 · {meta.label}
      </div>
      <div className={styles.prBody}>
        {diff ? (
          <>
            <div className={styles.diff}>
              <span className={styles.chip + ' ' + styles.chipWas}>{diff.was}</span>
              <span className={styles.diffArrow} aria-hidden="true">
                →
              </span>
              <span className={styles.chip + ' ' + styles.chipNow}>{diff.now}</span>
            </div>
            <div className={styles.prSub}>{action.human}</div>
          </>
        ) : (
          <div className={styles.prDesc}>{action.human}</div>
        )}
        {target || proposed ? (
          <div className={styles.prFacts}>
            {target ? (
              <div>
                <span>Target</span>
                <b>{target}</b>
              </div>
            ) : null}
            {proposed ? (
              <div>
                <span>Proposed</span>
                <b>{proposed}</b>
              </div>
            ) : null}
          </div>
        ) : null}
        {thinEvidence ? (
          <Alert
            className={styles.prAlert}
            type="warning"
            showIcon
            message="Evidence is limited. Review this change carefully before confirming."
          />
        ) : (
          <div className={styles.prEvidence}>
            <div className={styles.panelLabel}>Evidence used</div>
            <EvidenceList items={evidence.slice(0, 3)} compact />
          </div>
        )}
      </div>
      <div className={styles.prActions}>
        <Button type="primary" className="op-ai-btn" loading={loading} onClick={onConfirm}>
          确认修改
        </Button>
        <Button disabled={loading} onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}
