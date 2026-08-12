import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Empty, Input, Modal, Skeleton, Tag, message } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, CompassOutlined } from '@ant-design/icons';
import {
  completeAdaptivePractice,
  AdaptivePracticeError,
  listAdaptivePracticePlans,
  listAdaptivePracticeRecommendations,
  startAdaptivePractice,
} from '@/services/adaptiveInterviewPractice';
import type {
  AdaptivePracticeAssessment,
  AdaptivePracticeFocus,
  AdaptivePracticePlan,
  AdaptivePracticeRecommendation,
} from '@/types/adaptiveInterviewPractice';
import styles from './AdaptiveInterviewPracticeWorkspace.module.css';

const SESSION_KEY = 'offerpilot:adaptive-practice:draft';

interface SessionDraft {
  candidate: AdaptivePracticeRecommendation | null;
  answer: string;
  reflection: string;
  assessment: AdaptivePracticeAssessment | null;
  startKey: string | null;
  completionKey: string | null;
  resultUnknown: boolean;
  pendingOperation: 'start' | 'complete' | null;
}

function restoreSession(): SessionDraft {
  const empty: SessionDraft = { candidate: null, answer: '', reflection: '', assessment: null, startKey: null, completionKey: null, resultUnknown: false, pendingOperation: null };
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return empty;
    return { ...empty, ...JSON.parse(raw) } as SessionDraft;
  } catch {
    return empty;
  }
}

const ASSESSMENTS: Array<{ value: AdaptivePracticeAssessment; label: string; detail: string }> = [
  { value: 'needs_work', label: '还需要练', detail: '关键步骤还不够顺畅' },
  { value: 'clearer', label: '更清楚了', detail: '结构已经明显改善' },
  { value: 'confident', label: '可以复用', detail: '能稳定用于下一次回答' },
];

function newKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export default function AdaptiveInterviewPracticeWorkspace({ focus }: { focus?: AdaptivePracticeFocus }) {
  const restored = useMemo(restoreSession, []);
  const [recommendations, setRecommendations] = useState<AdaptivePracticeRecommendation[]>([]);
  const [plans, setPlans] = useState<AdaptivePracticePlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [candidate, setCandidate] = useState<AdaptivePracticeRecommendation | null>(restored.candidate);
  const [active, setActive] = useState<AdaptivePracticePlan | null>(null);
  const [answer, setAnswer] = useState(restored.answer);
  const [reflection, setReflection] = useState(restored.reflection);
  const [assessment, setAssessment] = useState<AdaptivePracticeAssessment | null>(restored.assessment);
  const [startKey, setStartKey] = useState<string | null>(restored.startKey);
  const [completionKey, setCompletionKey] = useState<string | null>(restored.completionKey);
  const [resultUnknown, setResultUnknown] = useState(restored.resultUnknown);
  const [pendingOperation, setPendingOperation] = useState<'start' | 'complete' | null>(restored.pendingOperation);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const [next, history] = await Promise.all([
        listAdaptivePracticeRecommendations(),
        listAdaptivePracticePlans(),
      ]);
      setRecommendations(next);
      setPlans(history);
      const inProgress = history.find((item) => item.status === 'in_progress');
      if (inProgress) setActive(inProgress);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    const draft: SessionDraft = { candidate, answer, reflection, assessment, startKey, completionKey, resultUnknown, pendingOperation };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(draft));
  }, [candidate, answer, reflection, assessment, startKey, completionKey, resultUnknown, pendingOperation]);

  const orderedRecommendations = useMemo(() => {
    if (!focus) return recommendations;
    return [...recommendations].sort((left, right) => {
      const leftFocused = left.proposal_id === focus.proposalId && left.focus_id === focus.focusId;
      const rightFocused = right.proposal_id === focus.proposalId && right.focus_id === focus.focusId;
      return Number(rightFocused) - Number(leftFocused);
    });
  }, [focus, recommendations]);

  const confirmStart = async () => {
    if (!candidate || busy) return;
    const key = startKey ?? newKey('adaptive-practice-start');
    setStartKey(key);
    setBusy(true);
    try {
      const plan = await startAdaptivePractice(candidate, key);
      setActive(plan);
      setCandidate(null);
      setStartKey(null);
      setResultUnknown(false);
      setPendingOperation(null);
      setRecommendations((current) => current.filter((item) => item.focus_id !== plan.focus_id || item.proposal_id !== plan.proposal_id));
    } catch (cause) {
      if (cause instanceof AdaptivePracticeError && cause.code) {
        setStartKey(null);
        setCandidate(null);
        setResultUnknown(false);
        setPendingOperation(null);
        await load();
      } else {
        setResultUnknown(true);
        setPendingOperation('start');
      }
      message.error(cause instanceof Error ? cause.message : '暂时无法开始练习');
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    if (!active || !answer.trim() || !assessment || busy) return;
    const key = completionKey ?? newKey('adaptive-practice-complete');
    setCompletionKey(key);
    setBusy(true);
    try {
      const completed = await completeAdaptivePractice(active.id, {
        expected_revision: active.revision,
        response_text: answer,
        reflection_text: reflection,
        self_assessment: assessment,
        idempotency_key: key,
      });
      setPlans((current) => [completed, ...current.filter((item) => item.id !== completed.id)]);
      setActive(null);
      setAnswer('');
      setReflection('');
      setAssessment(null);
      setCompletionKey(null);
      setResultUnknown(false);
      setPendingOperation(null);
      sessionStorage.removeItem(SESSION_KEY);
      message.success('练习已完成并保存');
    } catch (cause) {
      if (cause instanceof AdaptivePracticeError && cause.code) {
        setCompletionKey(null);
        setResultUnknown(false);
        setPendingOperation(null);
        await load();
      } else {
        setResultUnknown(true);
        setPendingOperation('complete');
      }
      message.error(cause instanceof Error ? cause.message : '完成结果待确认，请使用原操作重试');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (error) return <Alert type="error" showIcon message="复盘训练暂时无法加载" action={<Button onClick={() => void load()}>重新加载</Button>} />;

  return (
    <div className={styles.workspace}>
      <section className={styles.hero}>
        <div className={styles.heroIcon}><CompassOutlined /></div>
        <div>
          <span className={styles.eyebrow}>基于真实复盘</span>
          <h2>把一个已确认的问题，练成下一次可复用的回答</h2>
          <p>这里没有综合分数，也不会自动调用 AI。每项训练都来自你保存的面试复盘。</p>
        </div>
        <div className={styles.heroMetric}><strong>{orderedRecommendations.length}</strong><span>待练建议</span></div>
      </section>

      {active ? (
        <section className={styles.activeGrid}>
          <div className={styles.practiceCard}>
            <div className={styles.sectionHeading}>
              <div><span className={styles.eyebrow}>练习进行中</span><h3>{active.title}</h3></div>
              <Tag color="processing" icon={<ClockCircleOutlined />}>进行中</Tag>
            </div>
            <div className={styles.promptBox}><span>本次练习</span><strong>{active.prompt}</strong></div>
            <label className={styles.fieldLabel} htmlFor="adaptive-answer">你的回答</label>
            <Input.TextArea id="adaptive-answer" aria-label="练习回答" disabled={resultUnknown} value={answer} onChange={(event) => setAnswer(event.target.value)} autoSize={{ minRows: 6, maxRows: 12 }} placeholder="先写结论，再补充关键事实和影响……" />
            <label className={styles.fieldLabel} htmlFor="adaptive-reflection">练完后的复盘（可选）</label>
            <Input.TextArea id="adaptive-reflection" aria-label="练习复盘" disabled={resultUnknown} value={reflection} onChange={(event) => setReflection(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="哪一步比上次更清楚？" />
            <div className={styles.assessmentGroup}>
              <span className={styles.fieldLabel}>这次练习后的感受</span>
              <div className={styles.assessmentOptions}>
                {ASSESSMENTS.map((item) => (
                  <Button key={item.value} disabled={resultUnknown} className={assessment === item.value ? styles.assessmentActive : styles.assessment} onClick={() => setAssessment(item.value)}>
                    <strong>{item.label}</strong><span>{item.detail}</span>
                  </Button>
                ))}
              </div>
            </div>
            {resultUnknown && pendingOperation === 'complete' ? <Alert type="warning" showIcon message="完成结果待确认，输入已冻结。" action={<Button size="large" onClick={() => void finish()}>使用原操作重试</Button>} /> : <Button type="primary" size="large" disabled={!answer.trim() || !assessment} loading={busy} onClick={() => void finish()}>完成本次练习</Button>}
          </div>
          <aside className={styles.evidencePanel}>
            <span className={styles.eyebrow}>为什么现在练</span>
            <p>{active.reason}</p>
            <span className={styles.evidenceLabel}>系统观察</span>
            <blockquote>{active.observation}</blockquote>
            <span className={styles.evidenceLabel}>冻结复盘来源</span>
            <blockquote>{active.source_excerpt}</blockquote>
            <Tag color={active.source_status === 'current' ? 'green' : 'warning'}>{active.source_status === 'current' ? '来源仍一致' : '来源已变化，历史保持冻结'}</Tag>
          </aside>
        </section>
      ) : null}

      {!active ? (
        <section className={styles.section}>
          <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>建议练习</span><h3>从一个真实卡点开始</h3></div></div>
          {orderedRecommendations.length ? <div className={styles.recommendationGrid}>{orderedRecommendations.map((item) => (
            <article key={`${item.proposal_id}:${item.focus_id}`} className={styles.recommendationCard}>
              <div><Tag color="purple">{item.company_name} · {item.position_name}</Tag><h4>{item.title}</h4><p>{item.observation}</p></div>
              <div className={styles.sourcePreview}><span>复盘原文</span><q>{item.source_excerpt}</q></div>
              <Button type="primary" size="large" onClick={() => setCandidate(item)}>查看并开始 <ArrowRightOutlined /></Button>
            </article>
          ))}</div> : <Empty description="当前没有新的复盘训练建议" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
        </section>
      ) : null}

      <section className={styles.section}>
        <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>完成记录</span><h3>你已经沉淀的练习</h3></div></div>
        <div className={styles.historyList}>{plans.filter((item) => item.status === 'completed').map((item) => (
          <details key={item.id} className={styles.historyCard}>
            <summary><span className={styles.historyIcon}><CheckCircleOutlined /></span><span><strong>{item.title}</strong><small>{item.company_name} · {item.position_name}</small></span><Tag color="success">已完成</Tag></summary>
            <div className={styles.historyBody}><div><span>你的回答</span><p>{item.response_text}</p></div>{item.reflection_text ? <div><span>练后复盘</span><p>{item.reflection_text}</p></div> : null}<div><span>冻结来源</span><p>{item.source_excerpt}</p></div></div>
          </details>
        ))}</div>
      </section>

      <Modal title="开始前确认" open={Boolean(candidate)} confirmLoading={busy} okText={resultUnknown && pendingOperation === 'start' ? '使用原操作重试' : '确认开始'} cancelText="暂不开始" cancelButtonProps={{ disabled: resultUnknown }} onOk={() => void confirmStart()} onCancel={() => { if (!busy && !resultUnknown) { setCandidate(null); setStartKey(null); } }}>
        {candidate ? <div className={styles.confirmation}><p>你将开始：<strong>{candidate.title}</strong></p><div><span>为什么建议现在练</span><p>{candidate.reason}</p></div><div><span>使用的冻结来源</span><blockquote>{candidate.source_excerpt}</blockquote></div><Alert type="info" showIcon message="只有确认后才会创建练习记录；不会调用 AI。" /></div> : null}
      </Modal>
    </div>
  );
}
