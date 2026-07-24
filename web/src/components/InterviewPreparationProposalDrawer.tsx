import { useMemo, useState } from 'react';
import {
  createInterviewPreparationProposal,
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

interface Props {
  open: boolean;
  context: InterviewPreparationDrawerContext;
  onClose: () => void;
  onAttemptStateChange?: (state: { key: string; result_unknown: boolean } | null) => void;
  initialProposal?: InterviewPreparationProposal | null;
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
  initialProposal = null,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<InterviewPreparationProposal | null>(initialProposal);
  const [attemptKey, setAttemptKey] = useState(newAttemptKey);
  const hasInput = Boolean(context.resumeId && context.jdText.trim());
  const isSafeEmpty = proposal?.proposal_status === 'safe_empty';
  const input = useMemo<CreateInterviewPreparationProposalInput>(() => ({
    application_id: context.applicationId,
    event_id: context.eventId,
    resume_id: context.resumeId,
    jd_text: context.jdText,
    knowledge_selections: context.knowledgeSelections,
    user_assertions: context.userAssertions,
    idempotency_key: attemptKey,
  }), [attemptKey, context]);

  if (!open) return null;

  const generate = async () => {
    if (!hasInput || busy) return;
    if (!window.confirm('仅 JD、所选简历和已确认 Knowledge Evidence 会发送给 AI；用户断言仅保存于本次快照，不会发送给 AI，也不作为建议依据。是否继续？')) return;
    setBusy(true);
    setError(null);
    try {
      const result = await createInterviewPreparationProposal(input);
      if ('proposal' in result) {
        setProposal(result);
        onAttemptStateChange?.(null);
        setAttemptKey(newAttemptKey());
      } else {
        onAttemptStateChange?.({ key: attemptKey, result_unknown: result.attempt_status === 'provider_unknown' });
      }
    } catch (caught) {
      const typedError = caught instanceof InterviewPreparationProposalError ? caught : null;
      const unknown = !typedError || typedError.code === 'interview_preparation_provider_error';
      onAttemptStateChange?.(unknown ? { key: attemptKey, result_unknown: true } : null);
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
      <dl>
        <dt>岗位描述</dt><dd>{context.jdText}</dd>
        <dt>选定简历</dt><dd>{context.resumeId}</dd>
        <dt>已确认 Knowledge Evidence</dt><dd>{context.knowledgeSelections.length} 条</dd>
      </dl>
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
        {busy ? '正在生成…' : '生成面试准备建议'}
      </button>
      <button type="button" onClick={onClose}>关闭</button>
    </section>
  );
}
