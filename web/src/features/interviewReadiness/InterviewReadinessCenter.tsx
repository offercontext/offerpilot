import { useEffect, useMemo, useState } from 'react';
import type { Application } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { Resume } from '@/types/resume';
import { getCurrentApplicationJd } from '@/services/applicationJdVersions';
import { createInterviewPracticeCase } from '@/services/interviewPracticeCases';
import {
  buildQuickPracticeReadiness,
  buildRealInterviewReadiness,
  type QuickPracticeDraft,
  type ReadinessItem,
} from './interviewReadinessModel';
import styles from './InterviewReadinessCenter.module.css';

export interface RealInterviewStudioContext {
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
  positionName: string;
  jdText: string;
  resumeId: number;
}

interface Props {
  applications?: Application[];
  events?: ScheduleEvent[];
  resumes?: Resume[];
  onOpenApplication?: (applicationId: number) => void;
  onOpenPreparation?: (applicationId: number, eventId: number) => void;
  onOpenStudio?: (context: RealInterviewStudioContext | QuickPracticeStudioContext) => void;
}

const STATUS_COPY: Record<ReadinessItem['status'], string> = {
  ready: '已就绪',
  needs_input: '需要补充',
  source_changed: '来源已变化',
  unknown: '暂时未知',
  unavailable: '暂时不可用',
};

function makeKey(prefix: string): string {
  return `${prefix}-${typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : Date.now()}`;
}

function Checklist({ items, onAction }: { items: ReadinessItem[]; onAction?: (item: ReadinessItem) => void }) {
  return (
    <div className={styles.checklist} aria-label="开始前检查">
      {items.map((item) => (
        <div className={styles.checkItem} key={item.key} data-status={item.status}>
          <span className={styles.checkIcon} aria-hidden="true">{item.status === 'ready' ? '✓' : '·'}</span>
          <div className={styles.checkCopy}>
            <div className={styles.checkHeading}>
              <strong>{item.label}</strong>
              <span className={styles.status}>{STATUS_COPY[item.status]}</span>
            </div>
            <p>{item.detail}</p>
          </div>
          {item.actionLabel && onAction ? (
            <button type="button" className={styles.inlineAction} onClick={() => onAction(item)}>{item.actionLabel}</button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export default function InterviewReadinessCenter({
  applications = [],
  events = [],
  resumes = [],
  onOpenApplication,
  onOpenPreparation,
  onOpenStudio,
}: Props) {
  const [mode, setMode] = useState<'real' | 'quick'>('real');
  const [applicationId, setApplicationId] = useState<number | null>(applications[0]?.id ?? null);
  const [eventId, setEventId] = useState<number | null>(null);
  const [resumeId, setResumeId] = useState<number | undefined>(resumes[0]?.id);
  const [jdState, setJdState] = useState<{ status: 'ready' | 'missing' | 'unknown'; id?: number; text?: string }>({ status: applications[0] ? 'unknown' : 'missing' });
  const [quickDraft, setQuickDraft] = useState<QuickPracticeDraft>({ positionName: '', jdText: '', jdConfirmed: false, resumeId: resumes[0]?.id });
  const [quickError, setQuickError] = useState<string | null>(null);
  const [creatingCase, setCreatingCase] = useState(false);

  const visibleApplications = useMemo(
    () => applications.filter((item) => !item.deleted_at && item.status !== 'closed'),
    [applications],
  );
  const interviewEvents = useMemo(
    () => events.filter((event) => event.event_type === 'interview' && Boolean(event.scheduled_at) && event.status !== 'cancelled' && (applicationId === null || event.application_id === applicationId)),
    [applicationId, events],
  );
  const selectedApplication = visibleApplications.find((item) => item.id === applicationId) ?? null;
  const selectedEvent = interviewEvents.find((item) => item.id === eventId) ?? interviewEvents[0] ?? null;
  const selectedResume = resumes.find((item) => item.id === resumeId && !item.deleted_at) ?? null;

  useEffect(() => {
    if (!applicationId) {
      setJdState({ status: 'missing' });
      return;
    }
    let active = true;
    setJdState({ status: 'unknown' });
    void getCurrentApplicationJd(applicationId).then((result) => {
      if (!active) return;
      setJdState(result.current ? { status: 'ready', id: result.current.id, text: result.current.jd_text } : { status: 'missing' });
    }).catch(() => {
      if (active) setJdState({ status: 'unknown' });
    });
    return () => { active = false; };
  }, [applicationId]);

  useEffect(() => {
    if (!interviewEvents.some((item) => item.id === eventId)) setEventId(interviewEvents[0]?.id ?? null);
  }, [eventId, interviewEvents]);

  const realReadiness = buildRealInterviewReadiness({
    application: selectedApplication ? { id: selectedApplication.id } : null,
    jd: jdState,
    resume: selectedResume ? { id: selectedResume.id } : null,
    event: selectedEvent ? { id: selectedEvent.id } : null,
  });
  const quickReadiness = buildQuickPracticeReadiness(quickDraft);
  const readiness = mode === 'real' ? realReadiness : quickReadiness;

  const startQuickPractice = async () => {
    if (!quickReadiness.ready || !quickDraft.resumeId) return;
    setQuickError(null);
    setCreatingCase(true);
    try {
      const practiceCase = await createInterviewPracticeCase({
        idempotencyKey: makeKey('quick-case'),
        positionName: quickDraft.positionName.trim(),
        jdText: quickDraft.jdText,
        resumeId: quickDraft.resumeId,
      });
      onOpenStudio?.({
        kind: 'quick_practice',
        caseId: practiceCase.id,
        positionName: practiceCase.position_name_snapshot,
        jdText: practiceCase.jd_text_snapshot,
        resumeId: practiceCase.resume_id,
      });
    } catch (error) {
      const code = (error as { response?: { data?: { error_code?: string } } })?.response?.data?.error_code;
      setQuickError(code === 'interview_practice_case_idempotency_conflict' ? '快速练习档案内容已变化，请重新确认后再试。' : '快速练习档案结果待确认，输入已冻结；请使用原 key 重试。');
    } finally {
      setCreatingCase(false);
    }
  };

  const actionFor = (item: ReadinessItem) => {
    if (item.key === 'application' && visibleApplications[0]) setApplicationId(visibleApplications[0].id);
    if (item.key === 'resume' && resumes[0]) setResumeId(resumes[0].id);
    if (item.key === 'event' && interviewEvents[0]) setEventId(interviewEvents[0].id);
    if (item.key === 'jd' && selectedApplication) {
      if (selectedEvent) onOpenPreparation?.(selectedApplication.id, selectedEvent.id);
      else onOpenApplication?.(selectedApplication.id);
    }
  };

  return (
    <section className={styles.surface} data-testid="interview-readiness-center" aria-labelledby="readiness-title">
      <div className={styles.hero}>
        <div>
          <span className={styles.kicker}>INTERVIEW ROOM / 01</span>
          <h1 id="readiness-title">面试准备中心</h1>
          <p>先把要带进面试的证据准备好，再进入一间只属于这次练习的工作台。</p>
        </div>
        <div className={styles.heroNote}><span className={styles.liveDot} /> 证据门控已开启</div>
      </div>

      <div className={styles.modeGrid} role="tablist" aria-label="练习模式">
        <button type="button" role="tab" aria-selected={mode === 'real'} className={styles.modeCard} data-active={mode === 'real'} onClick={() => setMode('real')}>
          <span className={styles.modeNumber}>01</span>
          <span className={styles.modeTitle}>围绕真实投递练习</span>
          <span className={styles.modeDescription}>绑定当前投递、已确认 JD、简历与已排期面试。</span>
          <span className={styles.modeMeta}>适合面试前的真实准备</span>
        </button>
        <button type="button" role="tab" aria-selected={mode === 'quick'} className={styles.modeCard} data-active={mode === 'quick'} onClick={() => setMode('quick')}>
          <span className={styles.modeNumber}>02</span>
          <span className={styles.modeTitle}>快速练习</span>
          <span className={styles.modeDescription}>只针对一个岗位开始，不创建虚假的投递或日程。</span>
          <span className={styles.modeMeta}>适合临时热身与探索岗位</span>
        </button>
      </div>

      <div className={styles.workspaceGrid}>
        <div className={styles.prepPanel}>
          <div className={styles.panelHeader}>
            <div><span className={styles.eyebrow}>START HERE</span><h2>开始前检查</h2></div>
            <span className={styles.roundBadge}>{readiness.ready ? '可以出发' : '还差一点'}</span>
          </div>
          {mode === 'real' ? (
            <>
              <div className={styles.controls}>
                <label>选择投递<select value={applicationId ?? ''} onChange={(event) => setApplicationId(event.target.value ? Number(event.target.value) : null)}><option value="">请选择投递</option>{visibleApplications.map((item) => <option key={item.id} value={item.id}>{item.company_name} · {item.position_name}</option>)}</select></label>
                <label>选择面试事件<select value={selectedEvent?.id ?? ''} onChange={(event) => setEventId(event.target.value ? Number(event.target.value) : null)}><option value="">请选择已排期面试</option>{interviewEvents.map((item) => <option key={item.id} value={item.id}>{item.round ? `第 ${item.round} 轮 · ` : ''}{new Date(item.scheduled_at).toLocaleString()}</option>)}</select></label>
                <label>选择简历<select value={resumeId ?? ''} onChange={(event) => setResumeId(event.target.value ? Number(event.target.value) : undefined)}><option value="">请选择已保存简历</option>{resumes.filter((item) => !item.deleted_at).map((item) => <option key={item.id} value={item.id}>{item.title || item.name || `简历 ${item.id}`}</option>)}</select></label>
              </div>
              <div className={styles.readOnlyJd} aria-live="polite">
                <span>当前 JD（只读）</span>
                <p>{jdState.status === 'ready' ? jdState.text : jdState.status === 'unknown' ? '正在读取当前已确认版本…' : '尚未找到当前已确认的岗位资料版本。'}</p>
              </div>
            </>
          ) : (
            <div className={styles.controls}>
              <label>岗位名称<input value={quickDraft.positionName} maxLength={200} placeholder="例如：后端工程师" onChange={(event) => setQuickDraft((current) => ({ ...current, positionName: event.target.value }))} /></label>
              <label>粘贴 JD<textarea value={quickDraft.jdText} rows={5} placeholder="粘贴你已核对的岗位描述原文，不抓取 URL。" onChange={(event) => setQuickDraft((current) => ({ ...current, jdText: event.target.value }))} /></label>
              <label className={styles.confirmLabel}><input type="checkbox" checked={quickDraft.jdConfirmed} onChange={(event) => setQuickDraft((current) => ({ ...current, jdConfirmed: event.target.checked }))} /> 已核对，本次按此岗位资料练习</label>
              <label>选择简历<select value={quickDraft.resumeId ?? ''} onChange={(event) => setQuickDraft((current) => ({ ...current, resumeId: event.target.value ? Number(event.target.value) : undefined }))}><option value="">请选择已保存简历</option>{resumes.filter((item) => !item.deleted_at).map((item) => <option key={item.id} value={item.id}>{item.title || item.name || `简历 ${item.id}`}</option>)}</select></label>
            </div>
          )}
          <Checklist items={readiness.items} onAction={actionFor} />
          {quickError ? <div className={styles.error} role="alert">{quickError}</div> : null}
          <button
            type="button"
            className={styles.primaryAction}
            disabled={!readiness.ready || creatingCase}
            onClick={() => {
              if (mode === 'quick') void startQuickPractice();
              else if (selectedApplication && selectedEvent && selectedResume && jdState.id && jdState.text) onOpenStudio?.({ kind: 'application_event', applicationId: selectedApplication.id, eventId: selectedEvent.id, resumeId: selectedResume.id, jdVersionId: jdState.id, jdText: jdState.text, companyName: selectedApplication.company_name, positionName: selectedApplication.position_name });
            }}
          >{creatingCase ? '正在冻结练习资料…' : '进入模拟面试'}<span aria-hidden="true">↗</span></button>
          <p className={styles.privacyNote}>进入后仍会保留人工确认、原 key 恢复和来源状态说明。未确认的语音转写只在浏览器处理。</p>
        </div>

        <aside className={styles.sidePanel} aria-label="面试说明">
          <div className={styles.sideBlock}><span className={styles.eyebrow}>WHAT GOES IN</span><h3>本次会带入什么</h3><p>冻结的 JD、已保存简历、你明确选择的准备建议，以及本次已确认的回答。</p></div>
          <div className={styles.sideBlock}><span className={styles.eyebrow}>WHAT STAYS LOCAL</span><h3>什么不会离开浏览器</h3><p>原始音频、临时转写、VAD 帧和 Haru 的位置只在本地处理或保存。</p></div>
          <div className={styles.sideBlock}><span className={styles.eyebrow}>AFTER PRACTICE</span><h3>练习结束后</h3><p>你可以查看确认过的回答与复盘入口。快速练习会标记为“快速练习”，不会出现在投递或日历里。</p></div>
        </aside>
      </div>
    </section>
  );
}
