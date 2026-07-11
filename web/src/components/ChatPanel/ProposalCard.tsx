import { createElement, useEffect, useId, useRef, useState } from 'react';
import { Alert, Button, DatePicker, Input, InputNumber, Select, Switch } from 'antd';
import dayjs from 'dayjs';
import type { PendingAction, PendingActionEditableField } from '@/types/chat';
import { STATUS_LABELS, type ApplicationStatus } from '@/types/application';
import { EVENT_TYPE_LABELS, type ScheduleEventType } from '@/types/event';
import { selectEvidence, type EvidenceItem, type EvidenceTarget } from './model';
import { toolMeta } from './capabilities';
import EvidenceList from './EvidenceList';
import {
  actionIdentity,
  changedEditableArgs,
  createProposalReviewState,
  editableFieldsForAction,
  syncProposalReviewState,
  type ProposalReviewState,
} from './proposalDraft';
import styles from './ChatPanel.module.css';

interface Props {
  action: PendingAction;
  loading: boolean;
  evidence: EvidenceItem[];
  onConfirm: (editedArgs?: Record<string, unknown>) => void;
  onCancel: (rejectionFeedback?: string) => void;
  onOpenEvidence?: (target: EvidenceTarget) => void;
}

const FIELD_LABELS: Record<string, string> = {
  status: '状态',
  company_name: '公司',
  position_name: '岗位',
  job_url: '岗位链接',
  source: '来源',
  notes: '备注',
  company: '公司',
  position: '岗位',
  round: '轮次',
  date: '日期',
  questions: '问题记录',
  self_reflection: '自我复盘',
  difficulty_points: '难点短板',
  mood: '感受',
  applied_at: '投递日期',
  title: '标题',
  deadline: '截止时间',
  event_type: '日程类型',
  subtype: '细分类型',
  scheduled_at: '日程时间',
  duration_minutes: '时长',
  location: '地点',
  remind_at: '提醒时间',
};

const SUBTYPE_LABELS: Record<string, string> = {
  assessment: '测评',
  technical: '技术面',
  hr: 'HR 面',
  final: '终面',
  written: '笔试',
};

const LONG_REVIEW_FIELDS = new Set(['questions', 'self_reflection', 'difficulty_points', 'mood', 'notes']);

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

function isScheduleEventType(value: unknown): value is ScheduleEventType {
  return typeof value === 'string' && value in EVENT_TYPE_LABELS;
}

function valueLabel(value: unknown, field?: string): string {
  if (value === null || value === undefined || value === '') return '空';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (field === 'status' && isApplicationStatus(value)) return STATUS_LABELS[value];
  if (isApplicationStatus(value)) return STATUS_LABELS[value];
  if (field === 'event_type' && isScheduleEventType(value)) return EVENT_TYPE_LABELS[value];
  if (field === 'subtype' && typeof value === 'string') return SUBTYPE_LABELS[value] ?? value;
  if ((field === 'scheduled_at' || field === 'remind_at') && typeof value === 'string') {
    const parsed = dayjs(value);
    return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : value;
  }
  if (field === 'duration_minutes') return `${value} 分钟`;
  return String(value);
}

function summarizeLongValue(value: unknown, field?: string): string | null {
  if (!field || !LONG_REVIEW_FIELDS.has(field) || typeof value !== 'string') return null;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= 80) return null;
  const paragraphs = value
    .split(/\n{2,}|(?:^|\s)(?=#{1,6}\s)|(?:^|\s)(?=\d+[.、]\s)/)
    .map((item) => item.trim())
    .filter(Boolean);
  const paragraphCount = Math.max(1, paragraphs.length);
  return `新增 ${paragraphCount} 段内容 · ${normalized.length} 字`;
}

export default function ProposalCard({ action, loading, evidence, onConfirm, onCancel, onOpenEvidence }: Props) {
  const identity = actionIdentity(action);
  const editorId = `proposal-editor-${useId().replace(/:/g, '')}`;
  const [review, setReview] = useState<ProposalReviewState>(() => createProposalReviewState(action));
  const pendingFocusTargetRef = useRef<'feedback' | 'trigger' | null>(null);

  useEffect(() => {
    setReview((current) => syncProposalReviewState(current, action));
  }, [action, identity]);

  const currentReview = syncProposalReviewState(review, action);
  const editableFields = editableFieldsForAction(action);

  useEffect(() => {
    if (review.identity !== identity || !pendingFocusTargetRef.current) return;
    const targetId =
      pendingFocusTargetRef.current === 'feedback'
        ? `${editorId}-feedback`
        : `${editorId}-reject-trigger`;
    document.getElementById(targetId)?.focus();
    pendingFocusTargetRef.current = null;
  }, [editorId, identity, review.identity, review.rejectOpen]);
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
  const visibleEvidence = selectEvidence(evidence.length ? evidence : actionEvidence, 3).visible;
  const changes = action.proposed_changes ?? [];
  const thinEvidence = visibleEvidence.length === 0;
  const longDraftFields = changes.filter((change) => summarizeLongValue(change.after, change.field));
  const confirmLabel = action.tool_name.includes('delete')
    ? '确认删除'
    : action.tool_name.includes('create') || action.tool_name === 'add_note'
      ? '确认新建'
      : '确认更新';
  const isDelete = action.tool_name.includes('delete');

  function updateReview(update: (current: ProposalReviewState) => ProposalReviewState) {
    setReview((current) => update(syncProposalReviewState(current, action)));
  }

  function updateDraft(field: string, value: unknown) {
    updateReview((current) => ({
      ...current,
      draft: { ...current.draft, [field]: value },
    }));
  }

  function setRejectOpen(open: boolean) {
    pendingFocusTargetRef.current = open ? 'feedback' : 'trigger';
    updateReview((current) => ({ ...current, rejectOpen: open }));
  }

  function renderEditorControl(descriptor: PendingActionEditableField) {
    const value = currentReview.draft[descriptor.field];
    const controlId = `${editorId}-${descriptor.field}`;
    const common = { id: controlId, disabled: loading, className: styles.editorControl };

    switch (descriptor.type) {
      case 'enum':
        return (
          <Select
            {...common}
            size="large"
            value={typeof value === 'string' ? value : undefined}
            options={(descriptor.options ?? []).map((option) => ({
              value: option,
              label: valueLabel(option, descriptor.field),
            }))}
            onChange={(next) => updateDraft(descriptor.field, next)}
          />
        );
      case 'boolean':
        return (
          <label className={styles.switchHitArea} htmlFor={controlId}>
            <Switch
              {...common}
              checked={value === true}
              checkedChildren="是"
              unCheckedChildren="否"
              onChange={(next) => updateDraft(descriptor.field, next)}
            />
          </label>
        );
      case 'number':
        return (
          <InputNumber
            {...common}
            size="large"
            precision={0}
            step={1}
            value={typeof value === 'number' && Number.isFinite(value) ? value : undefined}
            onChange={(next) =>
              typeof next === 'number' && Number.isFinite(next)
                ? updateDraft(descriptor.field, next)
                : updateDraft(
                    descriptor.field,
                    descriptor.clearable === true
                      ? descriptor.clear_value
                      : action.args?.[descriptor.field],
                  )
            }
          />
        );
      case 'datetime': {
        const parsed = typeof value === 'string' && value.trim() ? dayjs(value) : null;
        const dateValue = parsed?.isValid() ? parsed : null;
        return (
          <DatePicker
            {...common}
            size="large"
            showTime
            allowClear={descriptor.clearable === true}
            value={dateValue}
            format="YYYY-MM-DD HH:mm"
            onChange={(next) => {
              const nextValue = next?.isValid()
                ? next.toISOString()
                : descriptor.clearable === true
                  ? descriptor.clear_value
                  : action.args?.[descriptor.field];
              updateDraft(descriptor.field, nextValue);
            }}
          />
        );
      }
      case 'long_text':
        return (
          <Input.TextArea
            {...common}
            size="large"
            value={typeof value === 'string' ? value : ''}
            autoSize={{ minRows: 4, maxRows: 9 }}
            onChange={(event) => updateDraft(descriptor.field, event.target.value)}
          />
        );
      case 'string':
        return (
          <Input
            {...common}
            size="large"
            value={typeof value === 'string' ? value : ''}
            onChange={(event) => updateDraft(descriptor.field, event.target.value)}
          />
        );
    }
  }

  return (
    <div className={styles.proposal} role="group" aria-label="AI 修改提议">
      <div className={styles.prHead}>
        <span className={styles.prIcon} aria-hidden="true">
          {createElement(meta.icon)}
        </span>
        AI 想执行一个修改操作 · {meta.label}
      </div>
      <div className={styles.prBody}>
        {action.workflow ? (
          <div className={styles.workflowHint}>
            <span>
              第 {action.workflow.current_step} / {action.workflow.total_steps} 步 · {action.workflow.current_label}
            </span>
            {action.workflow.description ? <b>{action.workflow.description}</b> : null}
          </div>
        ) : null}
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
            {changes.map((change) => {
              const beforeText = valueLabel(change.before, change.field);
              const rawAfterText = valueLabel(change.after, change.field);
              const afterText = summarizeLongValue(change.after, change.field) ?? rawAfterText;
              return (
                <div key={change.field} className={styles.changeRow}>
                  <span>{fieldLabel(change.field)}</span>
                  <b className={styles.changeValue} title={beforeText}>
                    {beforeText}
                  </b>
                  <i aria-hidden="true">→</i>
                  <b className={styles.changeValue} title={rawAfterText}>
                    {afterText}
                  </b>
                </div>
              );
            })}
          </div>
        ) : null}
        {longDraftFields.length ? (
          <div className={styles.draftHint}>长内容已按摘要展示，确认后会完整保存。</div>
        ) : null}
        {action.draft_summary?.fields.length ? (
          <div className={styles.draftReview}>
            <div className={styles.panelLabel}>草稿审阅</div>
            {action.draft_summary.fields.map((field) => (
              <div key={field.field} className={styles.draftItem}>
                <span>{field.label}</span>
                <b title={field.summary}>{field.summary}</b>
                <i>{field.characters} 字</i>
              </div>
            ))}
          </div>
        ) : null}
        {editableFields.length ? (
          <div className={styles.proposalEditor}>
            <button
              type="button"
              className={styles.editorDisclosure}
              aria-expanded={currentReview.editorOpen}
              aria-controls={editorId}
              disabled={loading}
              onClick={() =>
                updateReview((current) => ({ ...current, editorOpen: !current.editorOpen }))
              }
            >
              <span>编辑建议</span>
              <i aria-hidden="true">{currentReview.editorOpen ? '收起' : '展开'}</i>
            </button>
            {currentReview.editorOpen ? (
              <div id={editorId} className={styles.editorGrid}>
                <p>只会提交这里实际修改过的字段，其余建议保持不变。</p>
                {editableFields.map((descriptor) => {
                  const controlId = `${editorId}-${descriptor.field}`;
                  return (
                    <div key={descriptor.field} className={styles.editorField}>
                      <label htmlFor={controlId}>{fieldLabel(descriptor.field)}</label>
                      {renderEditorControl(descriptor)}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        ) : null}
        {action.risk_hint || thinEvidence ? (
          <Alert
            className={styles.prAlert}
            type="warning"
            showIcon
            message={action.risk_hint ?? '参考依据较少，请确认内容无误后再执行。'}
          />
        ) : null}
        {!thinEvidence ? (
          <div className={styles.prEvidence}>
            <div className={styles.panelLabel}>参考依据</div>
            <EvidenceList items={visibleEvidence.slice(0, 3)} compact onOpenEvidence={onOpenEvidence} />
          </div>
        ) : null}
      </div>
      {currentReview.rejectOpen ? (
        <div
          className={styles.rejectPanel}
          role="region"
          aria-live="polite"
          aria-label={isDelete ? '保留记录确认' : '拒绝建议确认'}
        >
          <div>
            <b>{isDelete ? '确认保留这条记录？' : '最终拒绝这项建议？'}</b>
            <p>
              {isDelete
                ? '删除不会执行。你可以补充原因，帮助 Pilot 调整后续建议。'
                : '当前建议不会执行。反馈可选，并会用于后续对话。'}
            </p>
          </div>
          <label htmlFor={`${editorId}-feedback`}>拒绝原因（可选）</label>
          <Input.TextArea
            id={`${editorId}-feedback`}
            size="large"
            value={currentReview.feedback}
            maxLength={500}
            showCount
            autoSize={{ minRows: 3, maxRows: 6 }}
            disabled={loading}
            placeholder="例如：时间不对，先不要更新"
            onChange={(event) =>
              updateReview((current) => ({ ...current, feedback: event.target.value }))
            }
          />
          <div className={styles.rejectActions}>
            <button
              type="button"
              className={styles.reviewBack}
              disabled={loading}
              onClick={() => setRejectOpen(false)}
            >
              返回审核
            </button>
            <Button
              danger
              type="primary"
              loading={loading}
              onClick={() => onCancel(currentReview.feedback.trim() || undefined)}
            >
              {isDelete ? '确认不删除' : '最终拒绝'}
            </Button>
          </div>
        </div>
      ) : (
        <div className={styles.prActions}>
          <Button
            type="primary"
            className="op-ai-btn"
            loading={loading}
            onClick={() => onConfirm(changedEditableArgs(action, currentReview.draft))}
          >
            {confirmLabel}
          </Button>
          <Button
            id={`${editorId}-reject-trigger`}
            disabled={loading}
            onClick={() => setRejectOpen(true)}
          >
            {isDelete ? '不删除' : '拒绝建议'}
          </Button>
        </div>
      )}
    </div>
  );
}
