import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Drawer, Empty, Input, List, Select, Space, Spin, Tag,
} from 'antd';
import {
  confirmMockInterviewReviewDraft,
  finishMockInterview,
  generateMockInterviewQuestion,
  listMockInterviewHistory,
  startMockInterview,
  submitMockInterviewAnswer,
} from '@/services/mockInterviews';
import { listInterviewPreparationProposals } from '@/services/interviewPreparationProposals';
import type { InterviewPreparationProposal } from '@/types/interviewPreparationProposal';
import type {
  MockInterviewFeedbackBlock,
  MockInterviewHistoryItem,
  MockInterviewProposal,
} from '@/types/mockInterview';

export interface MockInterviewDrawerDraft {
  resumeId?: number;
  jdText: string;
  attemptKey: string | null;
  questionKey: string | null;
  feedbackKey: string | null;
  turnKey: string | null;
  nextQuestionKey: string | null;
  confirmationKey: string | null;
  answerSubmitted: boolean;
  editedBlocks: Record<string, string>;
  preparationProposalId?: number;
  attemptId: number | null;
  turnNo: number;
  question: string;
  answer: string;
  proposalId: number | null;
  proposal: MockInterviewProposal | null;
  selectedIds: string[];
  resultUnknown: boolean;
  error: string | null;
}

interface ResumeOption { id: number; title?: string; name?: string }

interface Props {
  open: boolean;
  applicationId: number;
  eventId: number;
  resumes: ResumeOption[];
  draft: MockInterviewDrawerDraft;
  onDraftChange: (patch: Partial<MockInterviewDrawerDraft>) => void;
  onClose: () => void;
}

function key(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `mock-interview-${Date.now()}`;
}

function blocks(proposal: MockInterviewProposal | null): MockInterviewFeedbackBlock[] {
  if (!proposal) return [];
  return [
    ...proposal.strengths,
    ...proposal.practice_points,
    ...proposal.follow_up_questions,
    ...proposal.next_practice_steps,
  ];
}

function safeError(error: unknown): string {
  const status = typeof error === 'object' && error !== null
    ? (error as { response?: { status?: number } }).response?.status
    : undefined;
  const code = typeof error === 'object' && error !== null
    ? (error as { response?: { data?: { error_code?: string } } }).response?.data?.error_code
    : undefined;
  if (status === 409) return '本次操作与已有结果冲突，请检查后重新开始。';
  if (code === 'mock_interview_unverifiable') return 'AI 输出未通过验证，请使用原尝试重试。';
  if (code === 'mock_interview_provider_error' || status === 502) return 'AI 服务暂不可用，结果待确认，请使用原尝试重试。';
  if (!status) return '操作结果待确认，请使用原尝试重试。';
  return status === 404
    ? '面试事件或投递已不可见，当前流程已关闭。'
    : status === 422
      ? '输入无法用于本次模拟面试，请检查简历和 JD。'
      : '操作结果待确认，请使用原尝试重试。';
}

export default function MockInterviewDrawer({
  open, applicationId, eventId, resumes, draft, onDraftChange, onClose,
}: Props) {
  const [history, setHistory] = useState<MockInterviewHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [working, setWorking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [preparations, setPreparations] = useState<InterviewPreparationProposal[]>([]);

  useEffect(() => {
    if (!open) return;
    setLoadingHistory(true);
    listMockInterviewHistory(applicationId, eventId)
      .then(setHistory)
      .catch(() => setHistory([]))
      .finally(() => setLoadingHistory(false));
  }, [applicationId, eventId, open]);

  useEffect(() => {
    if (!open) return;
    listInterviewPreparationProposals(applicationId)
      .then((items) => setPreparations(items.filter((item) => item.event_id === eventId && item.source_status !== 'source_changed')))
      .catch(() => setPreparations([]));
  }, [applicationId, eventId, open]);

  const selectedBlocks = useMemo(
    () => blocks(draft.proposal)
      .filter((item) => draft.selectedIds.includes(item.id))
      .map((item) => ({ ...item, text: draft.editedBlocks[item.id] ?? item.text })),
    [draft.proposal, draft.selectedIds, draft.editedBlocks],
  );
  const pending = draft.resultUnknown;

  const start = async () => {
    if (!draft.resumeId || !draft.jdText.trim()) return;
    const attemptKey = draft.attemptKey ?? key();
    const questionKey = draft.questionKey ?? key();
    onDraftChange({ attemptKey, questionKey, error: null });
    setWorking(true);
    try {
      const result = await startMockInterview({
        applicationId, eventId, resumeId: draft.resumeId, jdText: draft.jdText,
        attemptKey, questionKey, preparationProposalId: draft.preparationProposalId,
      });
      onDraftChange({
        attemptId: result.attempt_id,
        turnNo: result.turn.turn_no,
        question: result.turn.question,
        answer: result.turn.answer,
        resultUnknown: false,
        error: null,
      });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      onDraftChange({ resultUnknown: !status || status === 502, error: safeError(error) });
    } finally { setWorking(false); }
  };

  const answer = async () => {
    if (!draft.attemptId || !draft.answer.trim()) return;
    const turnKey = draft.turnKey ?? key();
    onDraftChange({ turnKey, error: null });
    setWorking(true);
    try {
      await submitMockInterviewAnswer({
        applicationId, eventId, attemptId: draft.attemptId, turnNo: draft.turnNo,
        answerText: draft.answer, turnKey,
      });
      onDraftChange({ error: null, resultUnknown: false, answerSubmitted: true });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      onDraftChange({ resultUnknown: !status || status === 502, error: safeError(error) });
    } finally { setWorking(false); }
  };

  const nextQuestion = async () => {
    if (!draft.attemptId || !draft.answerSubmitted) return;
    const nextQuestionKey = draft.nextQuestionKey ?? key();
    onDraftChange({ nextQuestionKey, error: null });
    setWorking(true);
    try {
      const result = await generateMockInterviewQuestion({
        applicationId, eventId, attemptId: draft.attemptId,
        turnNo: draft.turnNo + 1, questionKey: nextQuestionKey,
      });
      if (!('turn' in result)) {
        onDraftChange({ resultUnknown: true, error: '结果待确认，请使用原尝试重试。' });
        return;
      }
      onDraftChange({
        turnNo: result.turn.turn_no,
        question: result.turn.question,
        answer: result.turn.answer,
        answerSubmitted: false,
        nextQuestionKey: null,
        turnKey: null,
        resultUnknown: false,
        error: null,
      });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      onDraftChange({ resultUnknown: !status || status === 502, error: safeError(error) });
    } finally { setWorking(false); }
  };

  const finish = async () => {
    if (!draft.attemptId) return;
    const feedbackKey = draft.feedbackKey ?? key();
    onDraftChange({ feedbackKey, error: null });
    setWorking(true);
    try {
      const result = await finishMockInterview({ applicationId, eventId, attemptId: draft.attemptId, feedbackKey });
      if (!('proposal' in result)) {
        onDraftChange({ resultUnknown: true, error: '结果待确认，请使用原尝试重试。' });
        return;
      }
      onDraftChange({ proposalId: result.proposal_id, proposal: result.proposal, selectedIds: [], resultUnknown: false, error: null });
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      onDraftChange({ resultUnknown: !status || status === 502, error: safeError(error) });
    } finally { setWorking(false); }
  };

  const confirmDraft = async () => {
    if (!draft.attemptId || !draft.proposalId || selectedBlocks.length === 0) return;
    const confirmationKey = draft.confirmationKey ?? key();
    onDraftChange({ confirmationKey, error: null });
    setWorking(true);
    try {
      await confirmMockInterviewReviewDraft({
        applicationId, eventId, attemptId: draft.attemptId, proposalId: draft.proposalId,
        confirmationKey, selectedBlocks,
      });
      setConfirming(false);
      onDraftChange({ error: null });
    } catch (error) {
      onDraftChange({ error: safeError(error) });
    } finally { setWorking(false); }
  };

  return (
    <Drawer open={open} width={560} title="文本模拟面试" onClose={onClose}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <span style={{ color: 'var(--op-muted)' }}>仅用于练习表达。AI 不提供录用判断、通过率或岗位匹配分。</span>
        {draft.error ? <Alert type="warning" showIcon message={draft.error} /> : null}
        {pending ? <Alert type="info" message="结果待确认，请使用原尝试重试；输入已冻结。" /> : null}
        {!draft.attemptId && !draft.proposal ? (
          <>
            <Select
              aria-label="选择简历"
              placeholder="请选择本次使用的简历"
              style={{ width: '100%' }}
              value={draft.resumeId}
              onChange={(value) => onDraftChange({ resumeId: value })}
              options={resumes.map((resume) => ({ value: resume.id, label: resume.name ?? resume.title ?? `简历 ${resume.id}` }))}
            />
            <Input.TextArea
              aria-label="岗位 JD"
              placeholder="粘贴本次面试的 JD，不抓取链接"
              value={draft.jdText}
              onChange={(event) => onDraftChange({ jdText: event.target.value })}
              autoSize={{ minRows: 5, maxRows: 12 }}
            />
            {preparations.length > 0 ? (
              <Select
                allowClear
                aria-label="选择面试准备建议"
                placeholder="可选：选择已确认的面试准备建议"
                value={draft.preparationProposalId}
                onChange={(value) => onDraftChange({ preparationProposalId: value })}
                options={preparations.map((item) => ({ value: item.id, label: `准备建议 · ${new Date(item.created_at).toLocaleString()}` }))}
              />
            ) : null}
            <span style={{ color: 'var(--op-muted)' }}>本次输入将发送给当前配置的 AI 服务。请勿粘贴无关敏感信息。</span>
            <Button type="primary" onClick={() => void start()} disabled={!draft.resumeId || !draft.jdText.trim() || working}>
              开始文本模拟面试
            </Button>
          </>
        ) : null}
        {working && !draft.proposal ? <Spin tip="正在处理，请稍候" /> : null}
        {draft.attemptId && !draft.proposal ? (
          <>
            <h3>第 {draft.turnNo} 题</h3>
            <p>{draft.question || '请介绍一次与本次岗位相关的经历。'}</p>
            <Input.TextArea
              aria-label="回答"
              value={draft.answer}
              onChange={(event) => onDraftChange({ answer: event.target.value })}
              placeholder="输入你的回答"
              autoSize={{ minRows: 5, maxRows: 12 }}
            />
            <Button onClick={() => void answer()} disabled={!draft.answer.trim() || working}>提交回答</Button>
            <Button type="primary" onClick={() => void finish()} disabled={!draft.answer.trim() || working}>结束并生成复盘建议</Button>
          </>
        ) : null}
        {draft.attemptId && !draft.proposal && draft.answerSubmitted ? (
          <Button onClick={() => void nextQuestion()} disabled={working}>生成下一题</Button>
        ) : null}
        {draft.proposal ? (
          <>
            <Tag color={draft.proposal.proposal_status === 'safe_empty' ? 'default' : 'blue'}>
              {draft.proposal.proposal_status === 'safe_empty' ? '暂无可验证建议' : 'AI 建议（待人工确认）'}
            </Tag>
            {draft.proposal.proposal_status === 'safe_empty' ? (
              <Empty description="目前没有可验证、可给出的复盘建议" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : blocks(draft.proposal).map((item) => (
              <label key={item.id} style={{ display: 'block', marginBottom: 12 }}>
                <input
                  type="checkbox"
                  checked={draft.selectedIds.includes(item.id)}
                  onChange={(event) => onDraftChange({
                    selectedIds: event.target.checked
                      ? [...draft.selectedIds, item.id]
                      : draft.selectedIds.filter((id) => id !== item.id),
                  })}
                />{' '}
                <Input.TextArea
                  value={draft.editedBlocks[item.id] ?? item.text}
                  onChange={(event) => onDraftChange({ editedBlocks: { ...draft.editedBlocks, [item.id]: event.target.value } })}
                  autoSize={{ minRows: 2, maxRows: 5 }}
                />
                {item.evidence_refs.map((ref) => <span key={`${item.id}-${ref.path}`} style={{ color: 'var(--op-muted)' }}>（{ref.source}：{ref.excerpt}）</span>)}
              </label>
            ))}
            {draft.proposal.proposal_status === 'normal' && selectedBlocks.length > 0 && !confirming ? (
              <Button onClick={() => setConfirming(true)}>准备保存复盘草稿</Button>
            ) : null}
            {confirming ? (
              <Alert
                type="info"
                message="确认后将保存独立的模拟练习复盘草稿，不会覆盖正式复盘或写入知识库。"
                action={<Button type="primary" onClick={() => void confirmDraft()} disabled={working}>确认保存</Button>}
              />
            ) : null}
          </>
        ) : null}
        <section aria-label="历史模拟面试">
          <h3>历史记录（只读）</h3>
          {loadingHistory ? <Spin size="small" /> : null}
          {!loadingHistory && history.length === 0 ? <span style={{ color: 'var(--op-muted)' }}>暂无历史记录</span> : null}
          <List
            size="small"
            dataSource={history}
            renderItem={(item) => (
              <List.Item>
                <Space><span>{new Date(item.created_at).toLocaleString()}</span><Tag>{item.proposal_status === 'safe_empty' ? '暂无可验证建议' : '有复盘建议'}</Tag></Space>
              </List.Item>
            )}
          />
        </section>
      </Space>
    </Drawer>
  );
}
