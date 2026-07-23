import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import type { InterviewNote } from '@/types/note';
import type {
  InterviewReviewEvidenceRef,
  InterviewReviewProposal,
} from '@/types/interviewReviewProposal';
import {
  createInterviewReviewProposal,
  getInterviewReviewProposal,
  InterviewReviewProposalError,
  listInterviewReviewProposals,
} from '@/services/interviewReviewProposals';
import styles from './InterviewReviewProposalDrawer.module.css';

const { Paragraph, Text, Title } = Typography;

const EVIDENCE_LABELS: Record<InterviewReviewEvidenceRef['path'], string> = {
  '/questions': '复盘问题',
  '/self_reflection': '自我反思',
  '/difficulty_points': '困难点',
  '/mood': '情绪记录',
};

interface Props {
  open: boolean;
  note: InterviewNote;
  eventID?: number | null;
  onClose: () => void;
  attemptState?: InterviewReviewProposalAttemptState | null;
  onAttemptStateChange?: (state: InterviewReviewProposalAttemptState | null) => void;
}

export interface InterviewReviewProposalAttemptState {
  key: string;
  result_unknown: boolean;
}

function newAttemptKey() {
  return crypto.randomUUID?.() ?? `interview-review-${Date.now()}`;
}

function EvidenceRefs({ refs }: { refs: InterviewReviewEvidenceRef[] }) {
  if (refs.length === 0) return null;
  return (
    <div className={styles.evidence}>
      {refs.map((ref) => (
        <div key={`${ref.path}:${ref.excerpt}`}>
          <Tag>{EVIDENCE_LABELS[ref.path]}</Tag>
          <Text type="secondary">{ref.path}</Text>
          <Paragraph className={styles.excerpt}>“{ref.excerpt}”</Paragraph>
        </div>
      ))}
    </div>
  );
}

export default function InterviewReviewProposalDrawer({
  open,
  note,
  eventID,
  onClose,
  attemptState,
  onAttemptStateChange,
}: Props) {
  const [history, setHistory] = useState<InterviewReviewProposal[]>([]);
  const [selected, setSelected] = useState<InterviewReviewProposal | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const activeAttemptKey = useRef<string | null>(null);
  const currentEventID = eventID ?? note.application_event_id ?? null;
  const resultUnknown = attemptState?.result_unknown ?? false;
  const hasChangedSource = selected?.source_status === 'source_changed';
  const generationLabel = hasChangedSource ? '重新生成复盘建议' : '生成复盘建议';

  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setError('');
    setLoading(true);
    listInterviewReviewProposals(note.id)
      .then(setHistory)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '复盘建议暂时不可用，请稍后重试。'))
      .finally(() => setLoading(false));
  }, [open, note.id]);

  const selectedProposal = useMemo(() => selected, [selected]);

  async function openHistory(proposalID: number) {
    setLoading(true);
    setError('');
    try {
      setSelected(await getInterviewReviewProposal(note.id, proposalID));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '复盘建议暂时不可用，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    if (!currentEventID) {
      setError('请先绑定有效的面试事件。');
      return;
    }
    const key = hasChangedSource ? newAttemptKey() : (attemptState?.key ?? newAttemptKey());
    if (!window.confirm('本次复盘内容与面试事件信息将发送给当前配置的 AI 服务。是否继续？')) return;
    onAttemptStateChange?.({ key, result_unknown: false });
    activeAttemptKey.current = key;
    setGenerating(true);
    setError('');
    try {
      const proposal = await createInterviewReviewProposal(note.id, key);
      setHistory((items) => [proposal, ...items.filter((item) => item.id !== proposal.id)]);
      setSelected(proposal);
      onAttemptStateChange?.({ key, result_unknown: false });
    } catch (cause) {
      const safe = cause instanceof InterviewReviewProposalError ? cause : null;
      setError(safe?.message ?? '复盘建议暂时不可用，请稍后重试。');
      if (safe?.code) onAttemptStateChange?.(null);
      else {
        onAttemptStateChange?.({ key, result_unknown: true });
      }
    } finally {
      activeAttemptKey.current = null;
      setGenerating(false);
    }
  }

  function handleClose() {
    const key = activeAttemptKey.current ?? attemptState?.key;
    if (generating && key) {
      onAttemptStateChange?.({ key, result_unknown: true });
    }
    onClose();
  }

  if (!open) return null;

  return (
    <section className={styles.drawer} aria-label="面试复盘建议">
      <div className={styles.header}>
        <div>
          <Button type="link" onClick={handleClose}>返回复盘</Button>
          <Title level={3}>面试复盘建议</Title>
        </div>
        <Button onClick={handleClose}>关闭</Button>
      </div>

      <Card title="用户记录" size="small">
        <Paragraph><Text strong>面试问题：</Text>{note.questions || '未记录'}</Paragraph>
        <Paragraph><Text strong>自我反思：</Text>{note.self_reflection || '未记录'}</Paragraph>
        <Paragraph><Text strong>困难点：</Text>{note.difficulty_points || '未记录'}</Paragraph>
        <Paragraph><Text strong>情绪记录：</Text>{note.mood || '未记录'}</Paragraph>
      </Card>

      {error && <Paragraph type="danger" role="alert">{error}</Paragraph>}
      {resultUnknown && <Tag color="orange">结果待确认，请使用原尝试重试</Tag>}

      <Card title="历史建议" size="small" className={styles.history}>
        {loading ? <Spin /> : history.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有复盘建议" />
        ) : (
          <List
            dataSource={history}
            renderItem={(item) => (
              <List.Item>
                <Button type="link" onClick={() => void openHistory(item.id)}>
                  {new Date(item.created_at).toLocaleString()} {item.source_status === 'source_changed' ? '（来源已变化）' : ''}
                </Button>
              </List.Item>
            )}
          />
        )}
      </Card>

      {selectedProposal && (
        <Card title="AI 建议" size="small">
          {hasChangedSource && <Tag color="orange">来源已变化，请重新生成</Tag>}
          <Paragraph>{selectedProposal.proposal.summary.text}</Paragraph>
          <EvidenceRefs refs={selectedProposal.proposal.summary.evidence_refs} />
          <Title level={5}>已观察到的表现</Title>
          {selectedProposal.proposal.observations.map((item) => (
            <div key={item.id} className={styles.item}>
              <Paragraph>{item.text}</Paragraph>
              <EvidenceRefs refs={item.evidence_refs} />
            </div>
          ))}
          <Title level={5}>练习重点</Title>
          {selectedProposal.proposal.practice_focuses.map((item) => (
            <div key={item.id} className={styles.item}>
              <Paragraph>{item.text}</Paragraph>
              <EvidenceRefs refs={item.evidence_refs} />
            </div>
          ))}
          <Title level={5}>待澄清问题</Title>
          {[...selectedProposal.proposal.clarifications, ...selectedProposal.proposal.next_questions].map((item) => (
            <div key={item.id} className={styles.item}>
              <Paragraph>{item.question}</Paragraph>
              <EvidenceRefs refs={item.evidence_refs} />
            </div>
          ))}
          {!selectedProposal.proposal.observations.length && !selectedProposal.proposal.practice_focuses.length && (
            <Text type="secondary">当前没有可安全验证的表现或练习重点，请先补充待澄清问题。</Text>
          )}
        </Card>
      )}

      <Space>
        {(!selectedProposal || hasChangedSource) && (
          <Button type="primary" disabled={!currentEventID} loading={generating} onClick={() => void handleGenerate()}>
            {generationLabel}
          </Button>
        )}
        {!currentEventID && <Text type="secondary">请先绑定有效的面试事件。</Text>}
      </Space>
    </section>
  );
}
