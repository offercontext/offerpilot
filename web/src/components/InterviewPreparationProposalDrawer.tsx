import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createInterviewPreparationProposal,
  getInterviewPreparationProposal,
  listInterviewPreparationProposals,
  InterviewPreparationProposalError,
} from '@/services/interviewPreparationProposals';
import type {
  CreateInterviewPreparationProposalInput,
  InterviewPreparationItem,
  InterviewPreparationProposal,
} from '@/types/interviewPreparationProposal';

export interface InterviewPreparationDrawerContext {
  applicationId: number;
  eventId: number;
  resumeId: number;
  jdText: string;
  knowledgeSelections: Array<Record<string, unknown>>;
  userAssertions: string[];
}

export interface InterviewPreparationAttemptState {
  key: string;
  result_unknown: boolean;
}

export interface InterviewPreparationKnowledgeOption {
  note_version_id: number;
  evidence_id: string;
  label?: string;
  excerpt: string;
}

export interface InterviewPreparationDraft {
  attemptState: InterviewPreparationAttemptState;
  resumeId: number;
  jdText: string;
  assertionsText: string;
  knowledgeSelections: Array<Record<string, unknown>>;
}

interface Props {
  open: boolean;
  context: InterviewPreparationDrawerContext;
  onClose: () => void;
  onAttemptStateChange?: (state: { key: string; result_unknown: boolean } | null) => void;
  attemptState?: InterviewPreparationAttemptState;
  initialProposal?: InterviewPreparationProposal | null;
  resumeOptions?: Array<{ id: number; title?: string; name?: string }>;
  knowledgeOptions?: InterviewPreparationKnowledgeOption[];
  draft?: InterviewPreparationDraft;
  onDraftChange?: (draft: InterviewPreparationDraft | null) => void;
}

const SECTION_LABELS: Array<[keyof InterviewPreparationProposal['proposal'], string]> = [
  ['preparation_directions', '准备方向'],
  ['story_prompts', '经历故事提示'],
  ['review_points', '建议复习的知识点'],
  ['interviewer_questions', '可以向面试官确认的问题'],
  ['items_to_clarify', '当前资料不足，需要确认的信息'],
];

function newAttemptKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `interview-preparation-${Date.now()}`;
}

function safeErrorMessage(error: unknown): string {
  const typedError = error instanceof InterviewPreparationProposalError ? error : null;
  const errorRecord = typeof error === 'object' && error !== null ? error as Record<string, unknown> : null;
  const code = typedError?.code ?? (typeof errorRecord?.code === 'string' ? errorRecord.code : null);
  const status = typedError?.status ?? (typeof errorRecord?.status === 'number' ? errorRecord.status : 0);
  if (typedError || errorRecord) {
    if (code === 'interview_preparation_provider_error' || status === 502) {
      return 'AI 服务暂不可用，请稍后重试。';
    }
    if (code === 'interview_preparation_application_not_found') {
      return '该投递已不可见，请重新打开。';
    }
    if (code === 'interview_preparation_source_conflict') {
      return '准备依据已变化，请重新确认输入。';
    }
    if (status === 422) return '面试准备输入无法验证，请检查后重试。';
    if (status === 409) return '本次面试准备尝试已冲突，请重新开始。';
  }
  return '面试准备建议暂时不可用，请稍后重试。';
}

function Evidence({ item }: { item: InterviewPreparationItem }) {
  return (
    <div>
      {item.evidence_refs.map((ref, index) => (
        <div key={`${ref.source}-${ref.path}-${index}`}>
          <span>{ref.source === 'jd' ? '岗位描述' : ref.source === 'resume' ? '选定简历' : '已确认 Knowledge Evidence'}</span>
          <code>{ref.path}</code>
          <blockquote>{ref.excerpt}</blockquote>
        </div>
      ))}
    </div>
  );
}

export default function InterviewPreparationProposalDrawer({
  open,
  context,
  onClose,
  onAttemptStateChange,
  attemptState,
  initialProposal = null,
  resumeOptions = [],
  knowledgeOptions = [],
  draft,
  onDraftChange,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<InterviewPreparationProposal | null>(initialProposal);
  const [attemptKey, setAttemptKey] = useState(() => draft?.attemptState.key ?? attemptState?.key ?? newAttemptKey());
  const [resumeId, setResumeId] = useState(draft?.resumeId ?? context.resumeId);
  const [jdText, setJdText] = useState(draft?.jdText ?? context.jdText);
  const [assertionsText, setAssertionsText] = useState(draft?.assertionsText ?? context.userAssertions.join('\n'));
  const [history, setHistory] = useState<InterviewPreparationProposal[]>([]);
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>(() =>
    (draft?.knowledgeSelections ?? context.knowledgeSelections).flatMap((selection) =>
      Array.isArray(selection.evidence_ids)
        ? selection.evidence_ids.filter((value): value is string => typeof value === 'string')
        : [],
    ),
  );
  const suppressDraftPersistence = useRef(false);
  const hasInput = Boolean(resumeId && jdText.trim());
  const resultUnknown = attemptState?.result_unknown ?? draft?.attemptState.result_unknown ?? false;
  const isSafeEmpty = proposal?.proposal_status === 'safe_empty';
  const input = useMemo<CreateInterviewPreparationProposalInput>(() => ({
    application_id: context.applicationId,
    event_id: context.eventId,
    resume_id: resumeId,
    jd_text: jdText,
    knowledge_selections: knowledgeOptions.length > 0
      ? knowledgeOptions
        .filter((option) => selectedEvidenceIds.includes(option.evidence_id))
        .reduce<Array<{ note_version_id: number; evidence_ids: string[] }>>((groups, option) => {
          const group = groups.find((item) => item.note_version_id === option.note_version_id);
          if (group) group.evidence_ids.push(option.evidence_id);
          else groups.push({ note_version_id: option.note_version_id, evidence_ids: [option.evidence_id] });
          return groups;
        }, [])
      : context.knowledgeSelections,
    user_assertions: assertionsText.split('\n').map((value) => value.trim()).filter(Boolean),
    idempotency_key: attemptKey,
  }), [assertionsText, attemptKey, context, jdText, knowledgeOptions, resumeId, selectedEvidenceIds]);

  useEffect(() => {
    if (!open) return;
    void listInterviewPreparationProposals(context.applicationId)
      .then((items) => setHistory(items.filter((item) => item.event_id === context.eventId)))
      .catch(() => undefined);
  }, [context.applicationId, open]);

  useEffect(() => {
    if (!open || !onDraftChange || suppressDraftPersistence.current) {
      suppressDraftPersistence.current = false;
      return;
    }
    onDraftChange({
      attemptState: { key: attemptKey, result_unknown: attemptState?.result_unknown ?? false },
      resumeId,
      jdText,
      assertionsText,
      knowledgeSelections: input.knowledge_selections,
    });
  }, [assertionsText, attemptKey, attemptState?.result_unknown, input.knowledge_selections, jdText, onDraftChange, open, resumeId]);

  if (!open) return null;

  const generate = async () => {
    if (!hasInput || busy) return;
    if (!window.confirm('仅 JD、所选简历和已确认 Knowledge Evidence 会发送给 AI；用户断言仅保存于本次快照，不会发送给 AI，也不作为建议依据。是否继续？')) return;
    setBusy(true);
    setError(null);
    suppressDraftPersistence.current = false;
    try {
      const result = await createInterviewPreparationProposal(input);
      if ('proposal' in result) {
        setProposal(result);
        onAttemptStateChange?.(null);
        suppressDraftPersistence.current = true;
        onDraftChange?.(null);
        setAttemptKey(newAttemptKey());
      } else {
        onAttemptStateChange?.({ key: attemptKey, result_unknown: result.attempt_status === 'provider_unknown' });
      }
    } catch (caught) {
      const typedError = caught instanceof InterviewPreparationProposalError ? caught : null;
      const unknown =
        !typedError
        || typedError.code === null
        || typedError.code === 'interview_preparation_provider_error'
        || typedError.status >= 500;
      if (unknown) {
        onAttemptStateChange?.({ key: attemptKey, result_unknown: true });
      } else {
        onAttemptStateChange?.(null);
        suppressDraftPersistence.current = true;
        onDraftChange?.(null);
        setAttemptKey(newAttemptKey());
      }
      setError(safeErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="面试准备建议">
      <h2>面试准备建议</h2>
      <p>围绕当前面试事件，生成可审阅、可引用的准备建议。</p>
      <p>仅 JD、所选简历和已确认 Knowledge Evidence 会发送给 AI；用户断言仅保存于本次快照，不会发送给 AI。</p>
      {resultUnknown && (
        <p role="status">上次请求结果待确认，请使用原尝试重试；请不要修改输入。</p>
      )}
      <dl>
        <dt>岗位描述</dt><dd>{jdText || '尚未填写'}</dd>
        <dt>选定简历</dt><dd>{resumeId || '尚未选择'}</dd>
        <dt>已确认 Knowledge Evidence</dt><dd>{selectedEvidenceIds.length} 条</dd>
      </dl>
      {knowledgeOptions.length > 0 && (
        <fieldset>
          <legend>选择已确认 Knowledge Evidence</legend>
          {knowledgeOptions.map((option) => (
            <label key={option.evidence_id}>
              <input
                type="checkbox"
                disabled={resultUnknown}
                checked={selectedEvidenceIds.includes(option.evidence_id)}
                onChange={() => setSelectedEvidenceIds((current) => current.includes(option.evidence_id)
                  ? current.filter((id) => id !== option.evidence_id)
                  : [...current, option.evidence_id])}
              />
              {option.label || option.evidence_id}: {option.excerpt}
            </label>
          ))}
        </fieldset>
      )}
      <label>
        选择简历
        <select disabled={resultUnknown} value={resumeId} onChange={(event) => setResumeId(Number(event.target.value))}>
          <option value={0}>请选择简历</option>
          {resumeOptions.map((resume) => (
            <option key={resume.id} value={resume.id}>{resume.title || resume.name || `简历 ${resume.id}`}</option>
          ))}
        </select>
      </label>
      <label>
        粘贴 JD
        <textarea disabled={resultUnknown} value={jdText} onChange={(event) => setJdText(event.target.value)} placeholder="仅粘贴岗位描述文本，不会抓取链接。" />
      </label>
      <label>
        可选用户断言（不会发送给 AI）
        <textarea disabled={resultUnknown} value={assertionsText} onChange={(event) => setAssertionsText(event.target.value)} placeholder="每行一条本次准备的补充信息" />
      </label>
      {history.length > 0 && (
        <aside aria-label="历史面试准备建议">
          <h3>历史面试准备建议</h3>
          {history.map((item) => (
            <div key={item.id}>
              {item.source_status === 'source_changed' && (
                <p role="status">历史资料来源已变化，本提案仍保持冻结，可查看但不作为当前来源。</p>
              )}
              <button
                type="button"
                onClick={() => {
                  void getInterviewPreparationProposal(context.applicationId, item.id)
                    .then(setProposal)
                    .catch((caught) => setError(safeErrorMessage(caught)));
                }}
              >
                查看 {item.created_at}
              </button>
            </div>
          ))}
        </aside>
      )}
      {error && <p role="alert">{error}</p>}
      {isSafeEmpty && <p>暂无可验证的面试准备建议</p>}
      {proposal && !isSafeEmpty && SECTION_LABELS.map(([field, label]) => (
        <section key={field}>
          <h3>{label}</h3>
          {proposal.proposal[field].map((item) => (
            <article key={item.id}>
              <p>{item.text}</p>
              <Evidence item={item} />
            </article>
          ))}
        </section>
      ))}
      <button type="button" disabled={!hasInput || busy} onClick={() => void generate()}>
        {busy ? '正在生成…' : resultUnknown ? '使用原尝试重试' : '生成面试准备建议'}
      </button>
      <button type="button" onClick={onClose}>关闭</button>
    </section>
  );
}
