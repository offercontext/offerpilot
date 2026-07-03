import { Button } from 'antd';
import {
  SaveOutlined,
  ReloadOutlined,
  CloseOutlined,
  RightOutlined,
  CheckOutlined,
} from '@ant-design/icons';
import type { MockSession, MockFeedback } from '@/types/mock';
import RadarChart from './RadarChart';
import styles from './MockStudio.module.css';

interface Props {
  session: MockSession;
  feedback: MockFeedback;
  saving?: boolean;
  savedNoteId?: number | null;
  onSaveNote: () => void;
  onRetry: () => void;
  onClose: () => void;
  onJumpQuestion: (id: number) => void;
}

export default function MockResultCard({
  session,
  feedback,
  saving,
  savedNoteId,
  onSaveNote,
  onRetry,
  onClose,
  onJumpQuestion,
}: Props) {

  const axes = [
    { label: '综合', value: feedback.score_overall },
    { label: '表达', value: feedback.score_communication },
    { label: '深度', value: feedback.score_depth },
    { label: '结构', value: feedback.score_structure },
    { label: '自信', value: feedback.score_confidence },
  ];

  const scoreRows = [
    { label: '表达', value: feedback.score_communication },
    { label: '深度', value: feedback.score_depth },
    { label: '结构', value: feedback.score_structure },
    { label: '自信', value: feedback.score_confidence },
  ];

  return (
    <div className={`op-view-enter ${styles.result}`} style={{ animationDelay: '0s' }}>
      <div className={styles.card}>
        <div className={styles.resultHeader}>
          <div>
            <div className={styles.eyebrow}>📊 模拟面试报告</div>
            <h2 className={styles.resultTitle}>
              {session.role || '模拟面试'}
              {session.company ? ` · ${session.company}` : ''}
            </h2>
            <div className={styles.resultSub}>
              {session.round_type} · {session.difficulty} ·{' '}
              {session.question_count > 0 ? `${session.question_count} 题` : '不限题数'}
            </div>
          </div>
        </div>

        {/* Score panel */}
        <div className={styles.resultGrid}>
          <div className={styles.radarWrap}>
            <RadarChart axes={axes} />
          </div>
          <div className={styles.scorePanel} style={{ animationDelay: '0.08s' }}>
            <div className={styles.scoreOverall}>
              <span className={styles.scoreOverallNum}>{feedback.score_overall}</span>
              <span className={styles.scoreOverallUnit}>/ 100 综合分</span>
            </div>
            <div className={styles.scoreList}>
              {scoreRows.map((s, i) => (
                <div key={s.label} className={styles.scoreRow} style={{ animationDelay: `${0.12 + i * 0.04}s` }}>
                  <span className={styles.scoreLabel}>{s.label}</span>
                  <span className={styles.scoreBarWrap}>
                    <span
                      className={styles.scoreBar}
                      style={{ width: `${Math.max(0, Math.min(100, s.value))}%` }}
                    />
                  </span>
                  <span className={styles.scoreVal}>{s.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Summary */}
        <div className={styles.sectionTitle}>💬 总评</div>
        <p className={styles.summary}>{feedback.summary}</p>

        {/* Strengths / weaknesses */}
        <div className={styles.twoCol} style={{ animationDelay: '0.16s' }}>
          <div>
            <div className={styles.sectionTitle}>✅ 亮点</div>
            <div className={styles.tagList}>
              {feedback.strengths.length === 0 ? (
                <span style={{ color: 'var(--op-muted)', fontSize: 13 }}>暂无</span>
              ) : (
                feedback.strengths.map((s, i) => (
                  <div key={i} className={`${styles.tagItem} ${styles.tagGood}`}>
                    <span className={styles.tagDot} />
                    <span>{s}</span>
                  </div>
                ))
              )}
            </div>
          </div>
          <div>
            <div className={styles.sectionTitle}>⚠️ 待加强</div>
            <div className={styles.tagList}>
              {feedback.weaknesses.length === 0 ? (
                <span style={{ color: 'var(--op-muted)', fontSize: 13 }}>暂无</span>
              ) : (
                feedback.weaknesses.map((s, i) => (
                  <div key={i} className={`${styles.tagItem} ${styles.tagBad}`}>
                    <span className={styles.tagDot} />
                    <span>{s}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Drills */}
        <div className={styles.sectionTitle} style={{ animationDelay: '0.2s' }}>
          🎯 下一步行动（联动题库）
        </div>
        <div className={styles.drills}>
          {feedback.drills.length === 0 ? (
            <span style={{ color: 'var(--op-muted)', fontSize: 13 }}>暂无推荐</span>
          ) : (
            feedback.drills.map((d, i) => (
              <div key={i} className={styles.drillCard}>
                <div className={styles.drillArea}>{d.area}</div>
                <div className={styles.drillAction}>{d.action}</div>
                {d.link_question_ids && d.link_question_ids.length > 0 && (
                  <div className={styles.drillLinks}>
                    {d.link_question_ids.map((qid) => (
                      <button
                        key={qid}
                        type="button"
                        className={styles.drillLink}
                        onClick={() => onJumpQuestion(qid)}
                      >
                        去题库 #{qid}
                        <RightOutlined style={{ fontSize: 9, marginLeft: 3 }} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        <div className={styles.resultActions}>
          <Button
            type="primary"
            icon={savedNoteId ? <CheckOutlined /> : <SaveOutlined />}
            loading={saving}
            disabled={!!savedNoteId}
            onClick={onSaveNote}
          >
            {savedNoteId ? '已保存为复盘' : '保存为面试复盘'}
          </Button>
          <Button icon={<ReloadOutlined />} onClick={onRetry}>
            再练一次
          </Button>
          <Button icon={<CloseOutlined />} onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </div>
  );
}