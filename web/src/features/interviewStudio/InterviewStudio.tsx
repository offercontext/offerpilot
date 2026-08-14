import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Tag } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, FileTextOutlined, MenuOutlined, SendOutlined } from '@ant-design/icons';
import VoiceAnswerComposer, { type VoiceAnswerActivity } from '@/features/mockInterviewVoice/VoiceAnswerComposer';
import type { VoiceDeliverySummary } from '@/features/mockInterviewVoice/voiceDeliverySummary';
import {
  finishInterviewStudio,
  generateInterviewStudioQuestion,
  startInterviewStudioAttempt,
  submitInterviewStudioAnswer,
  type InterviewStudioContext as InterviewApiContext,
} from '@/services/mockInterviews';
import { saveInterviewStudioVoiceCoachingSnapshot } from '@/services/voiceCoaching';
import type { MockInterviewProposalResponse, MockInterviewTurn } from '@/types/mockInterview';
import {
  createStudioState,
  reduceStudioState,
  shouldGenerateNextQuestion,
  type StudioState,
} from './interviewStudioController';
import styles from './InterviewStudio.module.css';

export interface InterviewStudioContext {
  kind: 'application_event';
  applicationId: number;
  eventId: number;
  resumeId: number;
  jdVersionId: number;
  jdText: string;
  companyName?: string;
  positionName?: string;
}

export interface QuickPracticeStudioContext {
  kind: 'quick_practice';
  caseId: number;
  resumeId: number;
  positionName: string;
  jdText: string;
}

type Props = {
  context: InterviewStudioContext | QuickPracticeStudioContext;
  onClose: () => void;
  onActivityChange?: (activity: VoiceAnswerActivity) => void;
  onToggleHaru?: () => void;
};

type TimelineEntry = MockInterviewTurn & { confirmed?: boolean };

function key(prefix: string): string {
  return `${prefix}-${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : Date.now()}`;
}

function toServiceContext(context: Props['context']): InterviewApiContext {
  return context.kind === 'quick_practice'
    ? { kind: 'quick_practice', caseId: context.caseId }
    : { kind: 'application_event', applicationId: context.applicationId, eventId: context.eventId };
}

function isTurnResponse(value: Awaited<ReturnType<typeof startInterviewStudioAttempt>>): value is Extract<Awaited<ReturnType<typeof startInterviewStudioAttempt>>, { turn: MockInterviewTurn }> {
  return 'turn' in value;
}

function errorCopy(error: unknown): string {
  const response = (error as { response?: { status?: number; data?: { error_code?: string } } })?.response;
  const code = response?.data?.error_code;
  if (code === 'mock_interview_source_conflict') return '冻结来源暂时无法验证，请回到准备中心重新确认。';
  if (code === 'mock_interview_unverifiable') return 'AI 输出未通过验证，保留原 key，可安全重试。';
  if (code === 'mock_interview_question_result_unknown') return '下一题结果待确认，已保留原 question key。';
  if (response?.status === 422) return '当前回答或来源无法用于本次练习，请检查后重试。';
  if (response?.status === 409) return '本次操作与已有结果冲突，请使用原 key 对账。';
  return '网络或服务结果待确认，输入和原 key 已冻结。';
}

function questionLabel(turn: TimelineEntry): string {
  if (turn.question_kind === 'follow_up') return '追问';
  return '新话题';
}

export default function InterviewStudio({ context, onClose, onActivityChange, onToggleHaru }: Props) {
  const serviceContext = useMemo(() => toServiceContext(context), [context]);
  const attemptKeyRef = useRef(key('attempt'));
  const initialQuestionKeyRef = useRef(key('question'));
  const [state, setState] = useState<StudioState | null>(null);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [proposal, setProposal] = useState<MockInterviewProposalResponse | null>(null);
  const [voiceSubmitRevision, setVoiceSubmitRevision] = useState(0);
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [working, setWorking] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [voiceReview, setVoiceReview] = useState<{ turnNo: number; summary: VoiceDeliverySummary; saveState: 'idle' | 'saving' | 'saved' | 'unknown'; idempotencyKey: string } | null>(null);

  const update = (action: Parameters<typeof reduceStudioState>[1]) => {
    setState((current) => current ? reduceStudioState(current, action) : current);
  };

  const start = async () => {
    setStartError(null);
    setWorking(true);
    try {
      const result = await startInterviewStudioAttempt({
        context: serviceContext,
        resumeId: context.kind === 'application_event' ? context.resumeId : undefined,
        jdVersionId: context.kind === 'application_event' ? context.jdVersionId : undefined,
        attemptKey: attemptKeyRef.current,
        questionKey: initialQuestionKeyRef.current,
      });
      if (!isTurnResponse(result)) {
        setStartError('第一题结果待确认，输入已冻结。请使用原 key 重试。');
        return;
      }
      setAttemptId(result.attempt_id);
      setTimeline([{ ...result.turn, confirmed: false }]);
      setState(createStudioState({ turnNo: result.turn.turn_no, question: result.turn.question }));
    } catch (error) {
      setStartError(errorCopy(error));
    } finally {
      setWorking(false);
    }
  };

  useEffect(() => {
    void start();
    // A Studio instance owns one frozen context and one attempt key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceContext]);

  const appendConfirmedAnswer = (answer: string) => {
    setTimeline((current) => current.map((turn) => turn.turn_no === state?.turnNo ? { ...turn, answer, confirmed: true } : turn));
  };

  const generateNextQuestion = async (currentState: StudioState, currentAttemptId: number) => {
    const questionKey = currentState.questionKey ?? key('question');
    update({ type: 'question_submitting', questionKey });
    setWorking(true);
    try {
      const result = await generateInterviewStudioQuestion({
        context: serviceContext,
        attemptId: currentAttemptId,
        turnNo: currentState.turnNo + 1,
        questionKey,
      });
      if (!isTurnResponse(result)) {
        update({ type: 'result_unknown', operation: 'question', message: '下一题结果待确认，已保留原 question key。' });
        return;
      }
      setTimeline((current) => [...current, { ...result.turn, confirmed: false }]);
      update({ type: 'question_succeeded', turnNo: result.turn.turn_no, question: result.turn.question });
    } catch (error) {
      update({ type: 'result_unknown', operation: 'question', message: errorCopy(error) });
    } finally {
      setWorking(false);
    }
  };

  const submitAnswer = async () => {
    if (!state || !attemptId || !state.answer.trim() || working || state.resultUnknown) return;
    const turnKey = state.turnKey ?? key('turn');
    update({ type: 'answer_submitting', turnKey });
    setWorking(true);
    try {
      await submitInterviewStudioAnswer({ context: serviceContext, attemptId, turnNo: state.turnNo, answerText: state.answer, turnKey });
      appendConfirmedAnswer(state.answer);
      const reviewForTurn = voiceReview?.turnNo === state.turnNo ? voiceReview : null;
      if (reviewForTurn) {
        setVoiceReview({ ...reviewForTurn, saveState: 'saving' });
        try {
          await saveInterviewStudioVoiceCoachingSnapshot({
            context: serviceContext,
            attemptId,
            turnNo: state.turnNo,
            payload: {
              idempotency_key: reviewForTurn.idempotencyKey,
              total_duration_ms: reviewForTurn.summary.totalDurationMs,
              voiced_duration_ms: reviewForTurn.summary.voicedDurationMs,
              pause_count: reviewForTurn.summary.pauseCount,
              longest_pause_ms: reviewForTurn.summary.longestPauseMs,
              speech_rate_cpm: reviewForTurn.summary.speechRateCpm ?? null,
              filler_occurrences: reviewForTurn.summary.fillerOccurrences.map((item) => ({ text: item.text, count: item.count, transcript_offsets: item.transcriptOffsets })),
              reflection_text: '',
              focus_kind: null,
              origin_snapshot_id: null,
            },
          });
          setVoiceReview((current) => current ? { ...current, saveState: 'saved' } : current);
        } catch {
          setVoiceReview((current) => current ? { ...current, saveState: 'unknown' } : current);
        }
      }
      update({ type: 'answer_succeeded' });
      setVoiceSubmitRevision((revision) => revision + 1);
      const confirmedState = { ...state, phase: 'answer_confirmed' as const };
      if (shouldGenerateNextQuestion(confirmedState)) await generateNextQuestion(confirmedState, attemptId);
      else setState((current) => current ? reduceStudioState(current, { type: 'answer_succeeded' }) : current);
    } catch (error) {
      update({ type: 'result_unknown', operation: 'answer', message: errorCopy(error) });
    } finally {
      setWorking(false);
    }
  };

  const finish = async () => {
    if (!state || !attemptId || working || state.phase === 'answer_submitting' || state.phase === 'next_question_generating') return;
    const feedbackKey = state.feedbackKey ?? key('feedback');
    update({ type: 'feedback_submitting', feedbackKey });
    setWorking(true);
    try {
      const result = await finishInterviewStudio({ context: serviceContext, attemptId, feedbackKey });
      if (!('proposal' in result)) {
        update({ type: 'result_unknown', operation: 'feedback', message: '复盘结果待确认，已保留原 feedback key。' });
        return;
      }
      setProposal(result);
      setState((current) => current ? { ...current, pendingOperation: null, resultUnknown: false, phase: 'completed' } : current);
    } catch (error) {
      update({ type: 'result_unknown', operation: 'feedback', message: errorCopy(error) });
    } finally {
      setWorking(false);
    }
  };

  const retry = () => {
    if (startError) {
      void start();
      return;
    }
    if (!state || !attemptId) return;
    if (state.pendingOperation === 'answer') void submitAnswer();
    else if (state.pendingOperation === 'question') void generateNextQuestion(state, attemptId);
    else if (state.pendingOperation === 'feedback') void finish();
    else if (state.pendingOperation === 'start') void start();
  };

  const title = context.kind === 'quick_practice'
    ? `${context.positionName} · 快速练习`
    : `${context.companyName ?? '真实投递'} · ${context.positionName ?? '模拟面试'}`;
  const currentQuestion = state?.question ?? '正在准备第一题…';
  const canSubmit = Boolean(state?.answer.trim()) && !working && !state?.resultUnknown && state?.phase !== 'completed';
  const hasConfirmedAnswer = Boolean(state && timeline.some((turn) => turn.turn_no === state.turnNo && turn.confirmed));

  return (
    <div className={styles.studio} data-testid="interview-studio" role="dialog" aria-modal="true" aria-labelledby="interview-studio-title">
      <header className={styles.topbar}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={onClose}>退出工作台</Button>
        <div className={styles.titleBlock}>
          <span className={styles.kicker}>INTERVIEW STUDIO / {context.kind === 'quick_practice' ? 'QUICK' : 'LIVE'}</span>
          <h1 id="interview-studio-title">{title}</h1>
        </div>
        <div className={styles.topActions}>
          <span className={styles.round}>{state ? `第 ${state.turnNo} / ${state.maxTurns} 轮` : '准备中'}</span>
          <Tag color={startError ? 'orange' : 'green'}>{startError ? '结果待确认' : '来源已冻结'}</Tag>
          {onToggleHaru ? <Button type="text" icon={<MenuOutlined />} onClick={onToggleHaru}>显示 Haru</Button> : null}
          <Button onClick={() => void finish()} disabled={!attemptId || !state || working || Boolean(proposal)}>结束并生成复盘</Button>
        </div>
      </header>

      <main className={styles.main}>
        <section className={styles.timeline} aria-label="面试对话时间线">
          <div className={styles.timelineHeader}><div><span className={styles.kicker}>LIVE TRANSCRIPT</span><h2>保持对话，答案由你确认</h2></div><span className={styles.livePill}><i /> {state?.phase === 'result_unknown' ? '需要对账' : '本轮进行中'}</span></div>
          {startError ? <Alert className={styles.alert} type="warning" showIcon message={startError} action={<Button size="small" onClick={retry} disabled={working}>使用原 key 重试</Button>} /> : null}
          {state?.phase === 'result_unknown' && state.error ? <div tabIndex={-1}><Alert className={styles.alert} type="warning" showIcon message={state.error} action={<Button size="small" onClick={retry} disabled={working}>使用原 key 重试</Button>} /></div> : null}
          <div className={styles.turnList} aria-live="polite">
            {timeline.map((turn) => (
              <article key={turn.turn_no} className={`${styles.turn} ${turn.turn_no === state?.turnNo ? styles.activeTurn : ''}`}>
                <div className={styles.turnMarker}>{String(turn.turn_no).padStart(2, '0')}</div>
                <div className={styles.turnBody}>
                  <div className={styles.turnMeta}><span>面试官</span>{turn.turn_no > 1 ? <Tag>{questionLabel(turn)}</Tag> : null}<span className={styles.turnState}>{turn.confirmed ? '回答已确认' : turn.turn_no === state?.turnNo ? '等待回答' : ''}</span></div>
                  <h3>{turn.question}</h3>
                  {turn.answer ? <p className={styles.answerBubble}>{turn.answer}</p> : null}
                  {turn.turn_no === state?.turnNo && !turn.confirmed ? <span className={styles.questionHint}>当前问题 · 先回答，再由你确认提交</span> : null}
                </div>
              </article>
            ))}
            {!timeline.length ? <div className={styles.loadingTurn}><span className={styles.loader} />正在创建冻结 Attempt…</div> : null}
          </div>
          {state?.phase === 'next_question_generating' ? <div className={styles.generating} role="status" aria-live="polite"><span className={styles.loader} />正在根据已确认回答准备下一题…</div> : null}
          {voiceReview?.saveState === 'unknown' ? <Alert className={styles.alert} type="warning" showIcon message="表达复盘保存结果待确认，原保存 key 已保留。" /> : null}
          {state?.phase === 'completed' && !proposal ? <div className={styles.completeCard}><CheckCircleOutlined /><div><strong>本轮已完成</strong><span>你可以结束并生成复盘，或退出保留已确认的回答。</span></div></div> : null}
          {proposal ? <section className={styles.feedbackCard} aria-label="复盘建议"><span className={styles.kicker}>REFLECTION READY</span><h2>复盘建议已准备好</h2><p>建议只来自本次已确认回答与冻结来源。正式投递和快速练习会保持各自的来源边界。</p><ul>{[...proposal.proposal.strengths, ...proposal.proposal.practice_points, ...proposal.proposal.next_practice_steps].slice(0, 4).map((item) => <li key={item.id}>{item.text}</li>)}</ul></section> : null}
        </section>

        {evidenceOpen ? <aside className={styles.evidence} aria-label="本轮依据"><div className={styles.evidenceHeader}><div><span className={styles.kicker}>EVIDENCE RAIL</span><h2>本轮依据</h2></div><Button type="text" onClick={() => setEvidenceOpen(false)}>收起</Button></div><div className={styles.sourceCard}><FileTextOutlined /><div><strong>JD · 冻结版本</strong><p>{context.jdText || '当前 JD 为空'}</p></div></div><div className={styles.sourceCard}><FileTextOutlined /><div><strong>简历 · 已选快照</strong><p>已使用候选人确认的简历快照；原始内容不会在 Studio 中编辑。</p></div></div><div className={styles.sourceNote}>快速练习只关联 Practice Case，不会写入投递、日程、Knowledge、Memory、Story 或 Offer。</div></aside> : <Button className={styles.openEvidence} onClick={() => setEvidenceOpen(true)}>查看本轮依据</Button>}
      </main>

      <footer className={styles.composer} aria-label="回答区">
        <VoiceAnswerComposer
          question={currentQuestion}
          disabled={!state || Boolean(startError) || working || state?.phase === 'result_unknown' || state?.phase === 'completed' || state?.phase === 'next_question_generating'}
          textValue={state?.answer ?? ''}
          onTextChange={(answer) => update({ type: 'draft_changed', answer })}
          submitRevision={voiceSubmitRevision}
          onConfirmTranscript={(answer) => {
            update({ type: 'transcript_ready', answer });
            update({ type: 'transcript_confirmed' });
          }}
          onVoiceReviewConfirmed={(answer, summary) => {
            update({ type: 'transcript_ready', answer });
            update({ type: 'transcript_confirmed' });
            setVoiceReview({ turnNo: state?.turnNo ?? 1, summary, saveState: 'idle', idempotencyKey: key('voice') });
          }}
          onActivityChange={onActivityChange}
        />
        <div className={styles.submitBar}><span>{state?.answerMode === 'voice' ? '语音必须先核对文字，再进入同一个提交流程。' : '提交后回答会冻结，系统自动准备下一题。'}</span><Button type="primary" size="large" icon={<SendOutlined />} disabled={!canSubmit} onClick={() => void submitAnswer()}>确认并提交回答</Button></div>
        {hasConfirmedAnswer && state?.phase === 'answering' ? <span className={styles.confirmedHint}>回答已经发送，正在准备下一步…</span> : null}
      </footer>
    </div>
  );
}
