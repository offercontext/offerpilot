import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Tag } from 'antd';
import { ArrowLeftOutlined, CheckCircleOutlined, FileTextOutlined, MenuOutlined, SendOutlined } from '@ant-design/icons';
import VoiceAnswerComposer, { type VoiceAnswerActivity, type VoiceAnswerComposerCommand, type VoiceAnswerComposerEvent } from '@/features/mockInterviewVoice/VoiceAnswerComposer';
import {
  createContinuousVoiceSessionController,
  type ContinuousVoiceCommand,
  type ContinuousVoiceSessionController,
  type ContinuousVoiceState,
} from '@/features/mockInterviewVoice/continuousVoiceSessionController';
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
import { buildEvidenceEntries, evidenceKey, type StudioEvidenceEntry } from './evidenceLocator';
import styles from './InterviewStudio.module.css';
import ContinuousVoiceModePanel from './ContinuousVoiceModePanel';

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
  onEvidenceVisibilityChange?: (open: boolean) => void;
};

type TimelineEntry = MockInterviewTurn & { confirmed?: boolean };
type VoiceReview = {
  turnNo: number;
  summary: VoiceDeliverySummary;
  saveState: 'idle' | 'saving' | 'saved' | 'unknown';
  idempotencyKey: string;
};
type VoiceReviewRecovery = { attemptKey: string; attemptId: number | null; voiceReview: VoiceReview };
type StudioBusinessRecovery = { attemptKey: string; attemptId: number; state: StudioState; timeline: TimelineEntry[] };

const CONTINUOUS_VOICE_PREFERENCE_KEY = 'offerpilot:interview-studio:continuous-voice-preference';

function continuousActivity(status: ContinuousVoiceState['status']): VoiceAnswerActivity | undefined {
  if (status === 'reading_question') return 'speaking';
  if (status === 'waiting_for_speech') return 'waiting_for_speech';
  if (status === 'listening') return 'listening';
  if (status === 'end_candidate') return 'speech_paused';
  if (status === 'transcribing') return 'transcribing';
  if (status === 'reviewing_transcript') return 'reviewing_voice';
  if (status === 'fallback_standard') return 'idle';
  if (status === 'submitting_confirmed_answer' || status === 'generating_next_question') return 'preparing_voice';
  return undefined;
}

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
  if (code === 'mock_interview_feedback_result_unknown') return '复盘结果待确认，已保留原 feedback key。';
  if (response?.status === 422) return '当前回答或来源无法用于本次练习，请检查后重试。';
  if (response?.status === 409) return '本次操作与已有结果冲突，请使用原 key 对账。';
  return '网络或服务结果待确认，输入和原 key 已冻结。';
}

function questionLabel(turn: TimelineEntry): string {
  if (turn.question_kind === 'follow_up') return '追问';
  return '新话题';
}

function previewText(value: string, length = 180): string {
  const trimmed = value.trim();
  return trimmed.length > length ? `${trimmed.slice(0, length)}…` : trimmed;
}

function voiceRecoveryStorageKey(context: Props['context']): string {
  return context.kind === 'quick_practice'
    ? `offerpilot:interview-studio:voice-recovery:quick:${context.caseId}`
    : `offerpilot:interview-studio:voice-recovery:real:${context.applicationId}:${context.eventId}`;
}

function studioRecoveryStorageKey(context: Props['context']): string {
  return context.kind === 'quick_practice'
    ? `offerpilot:interview-studio:business-recovery:quick:${context.caseId}`
    : `offerpilot:interview-studio:business-recovery:real:${context.applicationId}:${context.eventId}`;
}

function readVoiceReviewRecovery(storageKey: string): VoiceReviewRecovery | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<VoiceReviewRecovery>;
    return parsed && typeof parsed.attemptKey === 'string' && parsed.voiceReview
      ? parsed as VoiceReviewRecovery
      : null;
  } catch {
    return null;
  }
}

function readStudioBusinessRecovery(storageKey: string): StudioBusinessRecovery | null {
  if (typeof window === 'undefined') return null;
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(storageKey) ?? 'null') as Partial<StudioBusinessRecovery> | null;
    return parsed
      && typeof parsed.attemptKey === 'string'
      && typeof parsed.attemptId === 'number'
      && parsed.state?.phase === 'result_unknown'
      && Array.isArray(parsed.timeline)
      ? parsed as StudioBusinessRecovery
      : null;
  } catch {
    return null;
  }
}

export default function InterviewStudio({ context, onClose, onActivityChange, onToggleHaru, onEvidenceVisibilityChange }: Props) {
  const studioRef = useRef<HTMLDivElement>(null);
  const questionHeadingRef = useRef<HTMLHeadingElement>(null);
  const onCloseRef = useRef(onClose);
  const closeRequestRef = useRef<() => void>(() => undefined);
  onCloseRef.current = onClose;
  const serviceContext = useMemo(() => toServiceContext(context), [context]);
  const recoveryStorageKey = useMemo(() => voiceRecoveryStorageKey(context), [context]);
  const studioRecoveryKey = useMemo(() => studioRecoveryStorageKey(context), [context]);
  const recoveryRef = useRef<VoiceReviewRecovery | null | undefined>(undefined);
  if (recoveryRef.current === undefined) recoveryRef.current = readVoiceReviewRecovery(recoveryStorageKey);
  const recovery = recoveryRef.current;
  const businessRecoveryRef = useRef<StudioBusinessRecovery | null | undefined>(undefined);
  if (businessRecoveryRef.current === undefined) businessRecoveryRef.current = readStudioBusinessRecovery(studioRecoveryKey);
  const businessRecovery = businessRecoveryRef.current;
  const attemptKeyRef = useRef(businessRecovery?.attemptKey ?? recovery?.attemptKey ?? key('attempt'));
  const initialQuestionKeyRef = useRef(key('question'));
  const startRetryTimerRef = useRef<number | null>(null);
  const startRequestRef = useRef(0);
  const initialQuestionFocusedRef = useRef(false);
  const [state, setState] = useState<StudioState | null>(() => businessRecovery?.state ?? null);
  const [continuousState, setContinuousState] = useState<ContinuousVoiceState>({
    status: 'disabled',
    generation: 0,
    question: '',
    transcript: '',
    countdownSeconds: null,
    error: null,
  });
  const [continuousCommand, setContinuousCommand] = useState<VoiceAnswerComposerCommand>();
  const [attemptId, setAttemptId] = useState<number | null>(() => businessRecovery?.attemptId ?? recovery?.attemptId ?? null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>(() => businessRecovery?.timeline ?? []);
  const [proposal, setProposal] = useState<MockInterviewProposalResponse | null>(null);
  const [voiceSubmitRevision, setVoiceSubmitRevision] = useState(0);
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const [jdExpanded, setJdExpanded] = useState(false);
  const [working, setWorking] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [voiceReview, setVoiceReview] = useState<VoiceReview | null>(() => recovery?.voiceReview ?? null);
  const [voiceDirty, setVoiceDirty] = useState(false);
  const voiceReviewRef = useRef<VoiceReview | null>(voiceReview);
  const continuousSubmitRef = useRef<(text: string) => void>();
  const continuousGenerateRef = useRef<() => void>();
  const continuousCommandIdRef = useRef(0);
  const continuousCleanupTimerRef = useRef<number | null>(null);
  const studioDisposedRef = useRef(false);
  const businessGenerationRef = useRef(0);
  const isBusinessRequestCurrent = (generation: number) => !studioDisposedRef.current && generation === businessGenerationRef.current;
  const onActivityChangeRef = useRef(onActivityChange);
  onActivityChangeRef.current = onActivityChange;
  voiceReviewRef.current = voiceReview;

  const continuousControllerRef = useRef<ContinuousVoiceSessionController>();
  if (!continuousControllerRef.current) {
    continuousControllerRef.current = createContinuousVoiceSessionController({
      onState: (next) => {
        if (studioDisposedRef.current) return;
        setContinuousState(next);
        const activity = continuousActivity(next.status);
        if (activity) onActivityChangeRef.current?.(activity);
      },
      onCommand: (command: ContinuousVoiceCommand) => {
        if (studioDisposedRef.current) return;
        if (command.type === 'submit_answer') {
          continuousSubmitRef.current?.(command.text);
          return;
        }
        if (command.type === 'generate_next_question') {
          continuousGenerateRef.current?.();
          return;
        }
        if (command.type === 'preflight' || command.type === 'read_question' || command.type === 'start_recording'
          || command.type === 'stop_recording' || command.type === 'start_transcription' || command.type === 'pause_capture' || command.type === 'resume_capture'
          || command.type === 'cleanup') {
          setContinuousCommand({ id: ++continuousCommandIdRef.current, type: command.type });
        }
      },
    });
  }
  const continuousController = continuousControllerRef.current;

  useEffect(() => {
    studioDisposedRef.current = false;
    if (continuousCleanupTimerRef.current !== null) {
      window.clearTimeout(continuousCleanupTimerRef.current);
      continuousCleanupTimerRef.current = null;
    }
    return () => {
      continuousCleanupTimerRef.current = window.setTimeout(() => {
        studioDisposedRef.current = true;
        businessGenerationRef.current += 1;
        continuousSubmitRef.current = undefined;
        continuousGenerateRef.current = undefined;
        continuousController.close();
        continuousCleanupTimerRef.current = null;
      }, 0);
    };
    // The deferred cleanup survives React StrictMode's effect probe without creating a second controller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      if (voiceReview?.saveState === 'unknown') {
        if (attemptId !== null) {
          window.sessionStorage.setItem(recoveryStorageKey, JSON.stringify({ attemptKey: attemptKeyRef.current, attemptId, voiceReview }));
        }
      } else if (voiceReview?.saveState === 'saved') {
        window.sessionStorage.removeItem(recoveryStorageKey);
      }
    } catch {
      // Session storage is only a best-effort recovery aid; the server remains authoritative.
    }
  }, [attemptId, recoveryStorageKey, voiceReview]);

  useEffect(() => {
    if (state?.phase !== 'result_unknown' || attemptId === null) return;
    try {
      window.sessionStorage.setItem(studioRecoveryKey, JSON.stringify({
        attemptKey: attemptKeyRef.current,
        attemptId,
        state,
        timeline,
      } satisfies StudioBusinessRecovery));
    } catch {
      // Session storage is only a best-effort recovery aid; the server remains authoritative.
    }
  }, [attemptId, state, studioRecoveryKey, timeline]);

  const clearStudioBusinessRecovery = () => {
    businessRecoveryRef.current = null;
    try { window.sessionStorage.removeItem(studioRecoveryKey); } catch { /* best effort */ }
  };

  useEffect(() => {
    const studio = studioRef.current;
    if (!studio) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    const siblings = studio.parentElement
      ? Array.from(studio.parentElement.children)
        .filter((element) => element !== studio && !(element as HTMLElement).hasAttribute('data-interview-studio-companion'))
        .map((element) => ({ element: element as HTMLElement, inert: Boolean((element as HTMLElement & { inert?: boolean }).inert) }))
      : [];

    document.body.style.overflow = 'hidden';
    for (const sibling of siblings) (sibling.element as HTMLElement & { inert?: boolean }).inert = true;
    (studio.querySelector<HTMLElement>('.topbar button') ?? studio).focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRequestRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(studio.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter((element) => !element.hidden);
      if (!focusable.length) {
        event.preventDefault();
        studio.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    studio.addEventListener('keydown', onKeyDown);
    return () => {
      studio.removeEventListener('keydown', onKeyDown);
      for (const sibling of siblings) (sibling.element as HTMLElement & { inert?: boolean }).inert = sibling.inert;
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
    // A Studio keeps one focus trap for its lifetime; the callback is read from a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    onEvidenceVisibilityChange?.(evidenceOpen);
  }, [evidenceOpen, onEvidenceVisibilityChange]);

  useEffect(() => {
    if (initialQuestionFocusedRef.current || !state || !timeline.length) return;
    const frame = window.requestAnimationFrame(() => {
      questionHeadingRef.current?.focus();
      initialQuestionFocusedRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [state, timeline.length]);

  const update = (action: Parameters<typeof reduceStudioState>[1]) => {
    setState((current) => current ? reduceStudioState(current, action) : current);
  };

  const handleContinuousEvent = (event: VoiceAnswerComposerEvent) => {
    switch (event.type) {
      case 'preflight_succeeded':
        continuousController.preflightSucceeded();
        break;
      case 'preflight_failed':
        continuousController.preflightFailed(event.message);
        break;
      case 'question_read_finished':
        continuousController.questionReadFinished();
        break;
      case 'speech_detected':
        continuousController.speechDetected();
        break;
      case 'silence_detected':
        continuousController.silenceDetected();
        break;
      case 'page_hidden':
        continuousController.pause();
        break;
      case 'recording_stopped':
        continuousController.recordingStopped();
        break;
      case 'review_available':
        continuousController.transcriptReady('');
        break;
      case 'recording_reset':
        continuousController.recordingReset();
        break;
      case 'error':
        continuousController.fallback(event.message);
        break;
      case 'recording_started':
        break;
    }
  };

  const cancelStartRetry = () => {
    if (startRetryTimerRef.current !== null) {
      window.clearTimeout(startRetryTimerRef.current);
      startRetryTimerRef.current = null;
    }
  };

  const start = async () => {
    cancelStartRetry();
    const requestId = ++startRequestRef.current;
    const businessGeneration = businessGenerationRef.current;
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
      if (requestId !== startRequestRef.current || !isBusinessRequestCurrent(businessGeneration)) return;
      if (!isTurnResponse(result)) {
        setStartError('第一题结果待确认，输入已冻结。请使用原 key 重试。');
        const retryAfterMs = 'retry_after_ms' in result && typeof result.retry_after_ms === 'number'
          ? Math.max(250, Math.min(5000, result.retry_after_ms))
          : 1000;
        if (startRetryTimerRef.current === null) {
          startRetryTimerRef.current = window.setTimeout(() => {
            startRetryTimerRef.current = null;
            void start();
          }, retryAfterMs);
        }
        return;
      }
      if (startRetryTimerRef.current !== null) {
        window.clearTimeout(startRetryTimerRef.current);
        startRetryTimerRef.current = null;
      }
      setAttemptId(result.attempt_id);
      setTimeline([{ ...result.turn, confirmed: false }]);
      setState(createStudioState({ turnNo: result.turn.turn_no, question: result.turn.question }));
    } catch (error) {
      if (requestId !== startRequestRef.current || !isBusinessRequestCurrent(businessGeneration)) return;
      setStartError(errorCopy(error));
    } finally {
      if (requestId === startRequestRef.current && isBusinessRequestCurrent(businessGeneration)) setWorking(false);
    }
  };

  useEffect(() => {
    if (businessRecoveryRef.current) return;
    void start();
    return () => {
      startRequestRef.current += 1;
      cancelStartRetry();
    };
    // A Studio instance owns one frozen context and one attempt key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceContext]);

  const appendConfirmedAnswer = (answer: string) => {
    setTimeline((current) => current.map((turn) => turn.turn_no === state?.turnNo ? { ...turn, answer, confirmed: true } : turn));
  };

  const saveVoiceReview = async (review: VoiceReview, currentAttemptId: number): Promise<boolean> => {
    const businessGeneration = businessGenerationRef.current;
    if (!isBusinessRequestCurrent(businessGeneration)) return false;
    setVoiceReview((current) => current ? { ...current, saveState: 'saving' } : current);
    try {
      await saveInterviewStudioVoiceCoachingSnapshot({
        context: serviceContext,
        attemptId: currentAttemptId,
        turnNo: review.turnNo,
        payload: {
          idempotency_key: review.idempotencyKey,
          total_duration_ms: review.summary.totalDurationMs,
          voiced_duration_ms: review.summary.voicedDurationMs,
          pause_count: review.summary.pauseCount,
          longest_pause_ms: review.summary.longestPauseMs,
          speech_rate_cpm: review.summary.speechRateCpm ?? null,
          filler_occurrences: review.summary.fillerOccurrences.map((item) => ({ text: item.text, count: item.count, transcript_offsets: item.transcriptOffsets })),
          reflection_text: '',
          focus_kind: null,
          origin_snapshot_id: null,
        },
      });
      if (!isBusinessRequestCurrent(businessGeneration)) return false;
      setVoiceReview((current) => current ? { ...current, saveState: 'saved' } : current);
      return true;
    } catch {
      if (!isBusinessRequestCurrent(businessGeneration)) return false;
      setVoiceReview((current) => current ? { ...current, saveState: 'unknown' } : current);
      return false;
    }
  };

  const retryVoiceReview = async () => {
    if (!voiceReview || !attemptId || voiceReview.saveState !== 'unknown') return;
    await saveVoiceReview(voiceReview, attemptId);
  };

  const requestClose = () => {
    const hasUnconfirmedDraft = Boolean(state?.answer.trim())
      && state?.phase === 'answering'
      && !timeline.some((turn) => turn.turn_no === state?.turnNo && turn.confirmed);
    const hasPendingVoiceSave = voiceReview?.saveState === 'unknown'
      || voiceReview?.saveState === 'saving'
      || voiceDirty
      || state?.phase === 'result_unknown'
      || ['preflight', 'reading_question', 'waiting_for_speech', 'listening', 'end_candidate', 'transcribing', 'reviewing_transcript', 'submitting_confirmed_answer', 'generating_next_question', 'paused', 'result_unknown'].includes(continuousState.status);
    if ((hasUnconfirmedDraft || hasPendingVoiceSave) && !window.confirm('当前还有未确认的回答或待恢复的语音复盘，确定退出工作台吗？')) return;
    studioDisposedRef.current = true;
    startRequestRef.current += 1;
    cancelStartRetry();
    businessGenerationRef.current += 1;
    continuousSubmitRef.current = undefined;
    continuousGenerateRef.current = undefined;
    continuousController.close();
    onCloseRef.current();
  };
  closeRequestRef.current = requestClose;

  const generateNextQuestion = async (currentState: StudioState, currentAttemptId: number) => {
    const businessGeneration = businessGenerationRef.current;
    if (!isBusinessRequestCurrent(businessGeneration)) return;
    const questionKey = currentState.questionKey ?? key('question');
    if (continuousState.status === 'result_unknown') continuousController.retryNextQuestion();
    update({ type: 'question_submitting', questionKey });
    setWorking(true);
    try {
      const result = await generateInterviewStudioQuestion({
        context: serviceContext,
        attemptId: currentAttemptId,
        turnNo: currentState.turnNo + 1,
        questionKey,
      });
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      if (!isTurnResponse(result)) {
        continuousController.nextQuestionUnknown('下一题结果待确认，已保留原 question key。');
        update({ type: 'result_unknown', operation: 'question', message: '下一题结果待确认，已保留原 question key。' });
        return;
      }
      clearStudioBusinessRecovery();
      setTimeline((current) => [...current, { ...result.turn, confirmed: false }]);
      update({ type: 'question_succeeded', turnNo: result.turn.turn_no, question: result.turn.question });
      continuousController.nextQuestionReady(result.turn.question);
    } catch (error) {
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      update({ type: 'result_unknown', operation: 'question', message: errorCopy(error) });
      continuousController.nextQuestionUnknown(errorCopy(error));
    } finally {
      if (isBusinessRequestCurrent(businessGeneration)) setWorking(false);
    }
  };

  continuousGenerateRef.current = () => {
    if (state && attemptId) void generateNextQuestion(state, attemptId);
  };

  const submitAnswer = async (answerOverride?: string) => {
    const answer = (answerOverride ?? state?.answer ?? '').trim();
    const businessGeneration = businessGenerationRef.current;
    if (!state || !attemptId || !answer || working || !isBusinessRequestCurrent(businessGeneration)) return;
    const turnKey = state.turnKey ?? key('turn');
    if (continuousState.status === 'result_unknown') continuousController.retryAnswerSubmission();
    update({ type: 'answer_submitting', turnKey });
    setWorking(true);
    try {
      await submitInterviewStudioAnswer({ context: serviceContext, attemptId, turnNo: state.turnNo, answerText: answer, turnKey });
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      appendConfirmedAnswer(answer);
      const reviewForTurn = voiceReviewRef.current?.turnNo === state.turnNo ? voiceReviewRef.current : null;
      if (reviewForTurn) {
        await saveVoiceReview(reviewForTurn, attemptId);
      }
      clearStudioBusinessRecovery();
      update({ type: 'answer_succeeded' });
      setVoiceSubmitRevision((revision) => revision + 1);
      const confirmedState = { ...state, phase: 'answer_confirmed' as const };
      const hasNextQuestion = shouldGenerateNextQuestion(confirmedState);
      if (continuousState.status !== 'disabled' && continuousState.status !== 'fallback_standard') {
        continuousController.answerSubmissionSucceeded(hasNextQuestion);
        if (!hasNextQuestion) setState((current) => current ? reduceStudioState(current, { type: 'answer_succeeded' }) : current);
      } else if (hasNextQuestion) await generateNextQuestion(confirmedState, attemptId);
      else setState((current) => current ? reduceStudioState(current, { type: 'answer_succeeded' }) : current);
    } catch (error) {
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      update({ type: 'result_unknown', operation: 'answer', message: errorCopy(error) });
      continuousController.answerSubmissionUnknown(errorCopy(error));
    } finally {
      if (isBusinessRequestCurrent(businessGeneration)) setWorking(false);
    }
  };

  continuousSubmitRef.current = (answer) => { void submitAnswer(answer); };

  const finish = async () => {
    const businessGeneration = businessGenerationRef.current;
    if (!state || !attemptId || working || state.phase === 'answer_submitting' || state.phase === 'next_question_generating' || !isBusinessRequestCurrent(businessGeneration)) return;
    const feedbackKey = state.feedbackKey ?? key('feedback');
    update({ type: 'feedback_submitting', feedbackKey });
    setWorking(true);
    try {
      const result = await finishInterviewStudio({ context: serviceContext, attemptId, feedbackKey });
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      if (!('proposal' in result)) {
        update({ type: 'result_unknown', operation: 'feedback', message: '复盘结果待确认，已保留原 feedback key。' });
        return;
      }
      clearStudioBusinessRecovery();
      setProposal(result);
      setState((current) => current ? { ...current, pendingOperation: null, resultUnknown: false, phase: 'completed' } : current);
    } catch (error) {
      if (!isBusinessRequestCurrent(businessGeneration)) return;
      update({ type: 'result_unknown', operation: 'feedback', message: errorCopy(error) });
    } finally {
      if (isBusinessRequestCurrent(businessGeneration)) setWorking(false);
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
  const enableContinuous = () => {
    try { window.localStorage.setItem(CONTINUOUS_VOICE_PREFERENCE_KEY, 'true'); } catch { /* preference is best effort */ }
    continuousController.enable(currentQuestion);
  };
  const disableContinuous = () => {
    if (working) return;
    businessGenerationRef.current += 1;
    try { window.localStorage.setItem(CONTINUOUS_VOICE_PREFERENCE_KEY, 'false'); } catch { /* preference is best effort */ }
    continuousController.disable();
  };
  const fallbackContinuous = () => {
    continuousController.fallback('连续语音不可用，已保留标准回答。');
  };
  const continuousInProgress = !['disabled', 'fallback_standard', 'closed'].includes(continuousState.status);
  const canSubmit = Boolean(state?.answer.trim()) && !working && !state?.resultUnknown && state?.phase !== 'completed' && !continuousInProgress;
  const hasConfirmedAnswer = Boolean(state && timeline.some((turn) => turn.turn_no === state.turnNo && turn.confirmed));
  const currentTimelineTurn = timeline.find((turn) => turn.turn_no === state?.turnNo) ?? timeline[timeline.length - 1];
  const currentEvidence = buildEvidenceEntries(currentTimelineTurn?.basis_refs);
  const contextJdReference = {
    source: 'jd',
    path: '/jd/text',
    excerpt: previewText(context.jdText),
  };

  const focusEvidence = (entry: StudioEvidenceEntry) => {
    setEvidenceOpen(true);
    setSelectedEvidenceKey(entry.key);
  };

  useEffect(() => {
    if (!selectedEvidenceKey || !evidenceOpen) return;
    const frame = window.requestAnimationFrame(() => {
      const target = Array.from(document.querySelectorAll<HTMLElement>('[data-evidence-key]'))
        .find((element) => element.dataset.evidenceKey === selectedEvidenceKey);
      target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [evidenceOpen, selectedEvidenceKey]);

  return (
    <div ref={studioRef} className={styles.studio} data-testid="interview-studio" data-interview-studio role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby="interview-studio-title">
      <header className={styles.topbar}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => closeRequestRef.current()}>退出工作台</Button>
        <div className={styles.titleBlock}>
          <span className={styles.kicker}>{context.kind === 'quick_practice' ? '快速练习' : '真实投递'}</span>
          <h1 id="interview-studio-title">{title}</h1>
        </div>
        <div className={styles.topActions}>
          <span className={styles.round}>{state ? `第 ${state.turnNo} / ${state.maxTurns} 轮` : '准备中'}</span>
          <Tag color={startError ? 'orange' : 'green'}>{startError ? '结果待确认' : '来源已冻结'}</Tag>
          {onToggleHaru ? <Button type="text" icon={<MenuOutlined />} onClick={onToggleHaru}>显示 Haru</Button> : null}
          <Button onClick={() => void finish()} disabled={!attemptId || !state || working || Boolean(proposal) || state?.phase === 'result_unknown' || ['preflight', 'reading_question', 'waiting_for_speech', 'listening', 'end_candidate', 'transcribing', 'reviewing_transcript', 'submitting_confirmed_answer', 'generating_next_question', 'paused', 'result_unknown'].includes(continuousState.status)}>结束并生成复盘</Button>
        </div>
      </header>

      <main className={styles.main}>
        <section className={styles.timeline} aria-label="面试对话时间线">
          <div className={styles.timelineHeader}><div><span className={styles.kicker}>面试对话</span><h2>保持对话，答案由你确认</h2></div><span className={styles.livePill}><i /> {state?.phase === 'result_unknown' ? '需要对账' : '本轮进行中'}</span></div>
          {startError ? <Alert className={styles.alert} type="warning" showIcon message={startError} action={<Button size="small" onClick={retry} disabled={working}>使用原 key 重试</Button>} /> : null}
          {state?.phase === 'result_unknown' && state.error ? <div tabIndex={-1}><Alert className={styles.alert} type="warning" showIcon message={state.error} action={<Button size="small" onClick={retry} disabled={working}>使用原 key 重试</Button>} /></div> : null}
          <div className={styles.turnList} aria-live="polite">
            {timeline.map((turn) => (
              <article key={turn.turn_no} className={`${styles.turn} ${turn.turn_no === state?.turnNo ? styles.activeTurn : ''}`}>
                <div className={styles.turnMarker}>{String(turn.turn_no).padStart(2, '0')}</div>
                <div className={styles.turnBody}>
                  <div className={styles.turnMeta}><span>面试官</span>{turn.turn_no > 1 ? <Tag>{questionLabel(turn)}</Tag> : null}<span className={styles.turnState}>{turn.confirmed ? '回答已确认' : turn.turn_no === state?.turnNo ? '等待回答' : ''}</span></div>
                  <h3 ref={turn.turn_no === state?.turnNo ? questionHeadingRef : undefined} tabIndex={turn.turn_no === state?.turnNo ? -1 : undefined} data-interview-studio-question>{turn.question}</h3>
                  {turn.answer ? <p className={styles.answerBubble}>{turn.answer}</p> : null}
                  {buildEvidenceEntries(turn.basis_refs).length ? (
                    <div className={styles.turnEvidence} aria-label="提问依据" data-interview-studio-evidence-trigger>
                      <span className={styles.evidenceLabel}>提问依据</span>
                      {buildEvidenceEntries(turn.basis_refs).map((entry) => (
                        <button
                          key={entry.key}
                          type="button"
                          className={styles.evidenceLink}
                          onClick={() => focusEvidence(entry)}
                        >
                          {entry.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {turn.question_kind === 'follow_up' && turn.parent_turn_no ? (
                    <button
                      type="button"
                      className={styles.followUpLink}
                      data-interview-studio-follow-up
                      onClick={() => {
                        const entry = buildEvidenceEntries(turn.basis_refs)[0];
                        if (entry) focusEvidence(entry);
                      }}
                    >
                      上一轮回答 → 当前追问
                    </button>
                  ) : null}
                  {turn.turn_no === state?.turnNo && !turn.confirmed ? <span className={styles.questionHint}>当前问题 · 先回答，再由你确认提交</span> : null}
                </div>
              </article>
            ))}
            {!timeline.length ? <div className={styles.loadingTurn}><span className={styles.loader} />正在创建冻结 Attempt…</div> : null}
          </div>
          {state?.phase === 'next_question_generating' ? <div className={styles.generating} role="status" aria-live="polite"><span className={styles.loader} />正在根据已确认回答准备下一题…</div> : null}
          {voiceReview?.saveState === 'unknown' ? <Alert className={styles.alert} type="warning" showIcon message="表达复盘保存结果待确认，原保存 key 已保留。" action={<Button size="small" onClick={() => void retryVoiceReview()} disabled={working}>使用原 key 重试</Button>} /> : null}
          {state?.phase === 'completed' && !proposal ? <div className={styles.completeCard}><CheckCircleOutlined /><div><strong>本轮已完成</strong><span>你可以结束并生成复盘，或退出保留已确认的回答。</span></div></div> : null}
          {proposal ? <section className={styles.feedbackCard} aria-label="复盘建议"><span className={styles.kicker}>复盘建议</span><h2>复盘建议已准备好</h2><p>建议只来自本次已确认回答与冻结来源。正式投递和快速练习会保持各自的来源边界。</p><ul>{[...proposal.proposal.strengths, ...proposal.proposal.practice_points, ...proposal.proposal.next_practice_steps].slice(0, 4).map((item) => <li key={item.id}>{item.text}</li>)}</ul></section> : null}
        </section>

        {evidenceOpen ? (
          <aside className={styles.evidence} aria-label="本轮依据">
            <div className={styles.evidenceHeader}>
              <div><span className={styles.kicker}>本轮来源</span><h2>提问依据</h2></div>
              <Button type="text" onClick={() => setEvidenceOpen(false)}>收起</Button>
            </div>
            <div className={styles.sourceCard} data-evidence-key={evidenceKey(contextJdReference)} data-evidence-active={selectedEvidenceKey === evidenceKey(contextJdReference)} data-evidence-expanded={jdExpanded}>
              <FileTextOutlined />
              <div>
                <strong>JD · 冻结版本</strong>
                <p>{jdExpanded ? context.jdText : previewText(context.jdText)}</p>
                {context.jdText.length > 180 ? <button type="button" className={styles.expandEvidence} onClick={() => setJdExpanded((expanded) => !expanded)}>{jdExpanded ? '收起全文' : '展开全文'}</button> : null}
              </div>
            </div>
            <div className={styles.sourceCard}>
              <FileTextOutlined />
              <div><strong>简历 · 已选快照</strong><p>已使用候选人确认的第 {context.resumeId} 份简历快照；原始内容不会在 Studio 中编辑。</p></div>
            </div>
            <div className={styles.evidenceList} aria-label="当前问题引用">
              <strong>当前问题引用</strong>
              {currentEvidence.length ? currentEvidence.map((entry) => (
                <button
                  type="button"
                  key={entry.key}
                  className={styles.evidenceExcerpt}
                  data-evidence-key={entry.key}
                  data-evidence-active={selectedEvidenceKey === entry.key}
                  onClick={() => focusEvidence(entry)}
                >
                  <span>{entry.label}</span>
                  <q>{entry.excerpt}</q>
                </button>
              )) : <p className={styles.emptyEvidence}>当前问题的来源正在整理，旧历史仍保持只读。</p>}
            </div>
            <div className={styles.sourceNote}>快速练习只关联 Practice Case，不会写入投递、日程、Knowledge、Memory、Story 或 Offer。</div>
          </aside>
        ) : <Button className={styles.openEvidence} aria-label="查看本轮依据" data-interview-studio-evidence-trigger onClick={() => setEvidenceOpen(true)}>查看本轮依据</Button>}
      </main>

      <footer className={styles.composer} aria-label="回答区">
        <ContinuousVoiceModePanel
          status={continuousState.status}
          countdownSeconds={continuousState.countdownSeconds}
          error={continuousState.error}
          disabled={!state || working || Boolean(startError) || ['result_unknown', 'completed', 'next_question_generating', 'answer_submitting', 'feedback_submitting'].includes(state?.phase ?? '')}
          onEnable={enableContinuous}
          onDisable={disableContinuous}
          onSkipReading={() => continuousController.skipReading()}
          onCancelCountdown={() => continuousController.cancelEndCandidate()}
          onPause={() => continuousController.pause()}
          onResume={() => continuousController.resume()}
          onStop={() => continuousController.manualStop()}
          onFallback={fallbackContinuous}
        />
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
             const review = { turnNo: state?.turnNo ?? 1, summary, saveState: 'idle' as const, idempotencyKey: key('voice') };
             voiceReviewRef.current = review;
             setVoiceReview(review);
             if (continuousState.status === 'reviewing_transcript') {
               continuousController.confirmTranscript(answer);
               return;
             }
           }}
           onAnswerModeChange={(mode) => update({ type: 'answer_mode', mode })}
          continuous
          compact
          continuousCommand={continuousCommand}
          onContinuousEvent={handleContinuousEvent}
          onDirtyChange={setVoiceDirty}
          onActivityChange={onActivityChange}
        />
        <div className={styles.submitBar}><span>{state?.answerMode === 'voice' ? '语音必须先核对文字，再进入同一个提交流程。' : '提交后回答会冻结，系统自动准备下一题。'}</span><Button type="primary" size="large" icon={<SendOutlined />} disabled={!canSubmit} onClick={() => void submitAnswer()}>确认并提交回答</Button></div>
        {hasConfirmedAnswer && state?.phase === 'answering' ? <span className={styles.confirmedHint}>回答已经发送，正在准备下一步…</span> : null}
      </footer>
    </div>
  );
}
