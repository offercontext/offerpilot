import { createElement } from 'react';
import { Alert, Button } from 'antd';
import type { PendingAction } from '@/types/chat';
import { STATUS_LABELS, type ApplicationStatus } from '@/types/application';
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

const FIELD_LABELS: Record<string, string> = {
  status: '状态',
  company_name: '公司',
  position_name: '岗位',
  job_url: '岗位链接',
  source: '来源',
  notes: '备注',
  applied_at: '投递日期',
  title: '标题',
  deadline: '截止时间',
};

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
  if (typeof id === 'number' || typeof id === 'string') return `记录 #${id}`;
  const company = action.args?.company_name;
  const role = action.args?.position_name;
  if (typeof company === 'string' && typeof role === 'string') return `${company} · ${role}`;
  if (typeof company === 'string') return company;
  return null;
}

function proposedValue(action: PendingAction): string | null {
  const status = action.args?.status;
  if (typeof status === 'string' && status.trim()) return `状态 → ${valueLabel(status, 'status')}`;
  const title = action.args?.title;
  if (typeof title === 'string' && title.trim()) return `标题 → ${title}`;
  return null;
}

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

function isApplicationStatus(value: unknown): value is ApplicationStatus {
  return typeof value === 'string' && value in STATUS_LABELS;
}

function valueLabel(value: unknown, field?: string): string {
  if (value === null || value === undefined || value === '') return '空';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (field === 'status' && isApplicationStatus(value)) return STATUS_LABELS[value];
  if (isApplicationStatus(value)) return STATUS_LABELS[value];
  return String(value);
}

export default function ProposalCard({ action, loading, evidence, onConfirm, onCancel }: Props) {
  const meta = toolMeta(action.tool_name);
  const diff = parseDiff(action.human);
  const target = action.target?.title ?? actionTarget(action);
  const targetMeta = action.target?.meta;
  const proposed = proposedValue(action);
  const actionEvidence = action.evidence?.map((item) => ({
    id: item.id,
    kind: item.kind as EvidenceItem['kind'],
    title: item.title,
    meta: item.meta,
    snippet: item.snippet,
    source: item.source,
  })) ?? [];
  const visibleEvidence = evidence.length ? evidence : actionEvidence;
  const changes = action.proposed_changes ?? [];
  const thinEvidence = visibleEvidence.length === 0;

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
                <span>目标</span>
                <b>{targetMeta ? `${target} · ${targetMeta}` : target}</b>
              </div>
            ) : null}
            {proposed ? (
              <div>
                <span>建议变更</span>
                <b>{proposed}</b>
              </div>
            ) : null}
          </div>
        ) : null}
        {changes.length ? (
          <div className={styles.changeList}>
            {changes.map((change) => (
              <div key={change.field} className={styles.changeRow}>
                <span>{fieldLabel(change.field)}</span>
                <b>{valueLabel(change.before, change.field)}</b>
                <i aria-hidden="true">→</i>
                <b>{valueLabel(change.after, change.field)}</b>
              </div>
            ))}
          </div>
        ) : null}
        {thinEvidence ? (
          <Alert
            className={styles.prAlert}
            type="warning"
            showIcon
            message="参考依据较少，请确认内容无误后再执行。"
          />
        ) : (
          <div className={styles.prEvidence}>
            <div className={styles.panelLabel}>参考依据</div>
            <EvidenceList items={visibleEvidence.slice(0, 3)} compact />
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
