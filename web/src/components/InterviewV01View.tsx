import { useEffect, useState } from 'react';
import { Alert, Button, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import { ArrowRightOutlined, CompassOutlined } from '@ant-design/icons';
import { listInterviews } from '@/services/interviews';
import { listAdaptivePracticeRecommendations } from '@/services/adaptiveInterviewPractice';
import type { InterviewIndexItem } from '@/types/interviewIndex';
import type { AdaptivePracticeFocus, AdaptivePracticeRecommendation } from '@/types/adaptiveInterviewPractice';
import workflowStyles from './ui/WorkflowSurface.module.css';
import practiceStyles from './AdaptiveInterviewPracticeWorkspace.module.css';

const { Paragraph, Title } = Typography;

interface Props {
  onOpenApplication?: (applicationId: number) => void;
  onOpenPreparation?: (applicationId: number, eventId: number) => void;
  onOpenMockInterview?: (applicationId: number, eventId: number) => void;
  onOpenStoryLibrary?: (reviewNoteId?: number) => void;
  onOpenAdaptivePractice?: (focus: AdaptivePracticeFocus) => void;
}

export default function InterviewV01View({ onOpenApplication, onOpenPreparation, onOpenMockInterview, onOpenStoryLibrary, onOpenAdaptivePractice }: Props) {
  const [items, setItems] = useState<InterviewIndexItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [practice, setPractice] = useState<AdaptivePracticeRecommendation | null>(null);
  const [practiceError, setPracticeError] = useState(false);

  useEffect(() => {
    let active = true;
    listInterviews().then((result) => {
      if (active) setItems(result.items);
    }).catch(() => {
      if (active) setError(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const loadPractice = () => {
    setPracticeError(false);
    return listAdaptivePracticeRecommendations()
      .then((result) => setPractice(result[0] ?? null))
      .catch(() => { setPractice(null); setPracticeError(true); });
  };

  useEffect(() => { void loadPractice(); }, []);

  return (
    <div data-testid="interview-surface" className={`${workflowStyles.surface} op-view-enter`} style={{ padding: 24 }}>
      <div className="op-section-heading" style={{ marginBottom: 20 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>面试</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            查看已安排的面试事件、复盘、证据化建议和准备入口。
          </Paragraph>
        </div>
        {onOpenStoryLibrary ? <Button type="primary" data-story-audit="ui-library" onClick={() => onOpenStoryLibrary()}>面试故事库</Button> : null}
      </div>
      {practice && onOpenAdaptivePractice ? (
        <section className={practiceStyles.hero} style={{ marginBottom: 20 }}>
          <div className={practiceStyles.heroIcon}><CompassOutlined /></div>
          <div>
            <span className={practiceStyles.eyebrow}>下一项复盘训练</span>
            <h2>{practice.title}</h2>
            <p>{practice.observation}</p>
          </div>
          <Button type="primary" size="large" onClick={() => onOpenAdaptivePractice({ proposalId: practice.proposal_id, focusId: practice.focus_id })}>
            查看并开始 <ArrowRightOutlined />
          </Button>
        </section>
      ) : null}
      {practiceError && onOpenAdaptivePractice ? <Alert style={{ marginBottom: 20 }} type="warning" showIcon message="复盘训练建议暂时无法加载" action={<Button size="large" onClick={() => void loadPractice()}>重新加载建议</Button>} /> : null}
      {loading ? <Spin aria-label="正在加载面试列表" /> : null}
      {error ? <Alert type="error" showIcon message="面试列表暂时无法加载，请稍后重试。" /> : null}
      {!loading && !error && items.length === 0 ? (
        <div className="op-empty-state">
          <Empty description="暂无已安排的面试" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      ) : null}
      {!loading && !error && items.length > 0 ? (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item className={workflowStyles.listRow} actions={[
              <Button key="detail" type="link" onClick={() => onOpenApplication?.(item.application_id)}>
                查看投递详情
              </Button>,
              item.preparation_available ? (
                <Button key="prepare" type="link" onClick={() => onOpenPreparation?.(item.application_id, item.event_id)}>
                  准备面试
                </Button>
              ) : null,
              <Button key="mock" type="link" onClick={() => onOpenMockInterview?.(item.application_id, item.event_id)}>
                开始文本模拟面试
              </Button>,
              item.note_id && onOpenStoryLibrary ? (
                <Button key="story" type="link" onClick={() => onOpenStoryLibrary(item.note_id ?? undefined)}>
                  整理为故事
                </Button>
              ) : null,
            ]}>
              <List.Item.Meta
                title={`${item.company_name} · ${item.position_name}`}
                description={(
                  <Space wrap className="op-long-text">
                    <span>{new Date(item.scheduled_at).toLocaleString()}</span>
                    <Tag>{item.note_id ? '已有复盘' : '待记录复盘'}</Tag>
                    {item.review_summary ? <span>{item.review_summary}</span> : null}
                    {item.note_source_status === 'source_changed' ? <Tag color="warning">来源已变化</Tag> : null}
                    {item.has_review_proposal ? <Tag color="blue">有复盘建议</Tag> : null}
                    {item.has_confirmed_knowledge ? <Tag color="green">已有确认知识</Tag> : null}
                    {item.preparation_available ? <Tag>可准备面试</Tag> : null}
                  </Space>
                )}
              />
            </List.Item>
          )}
        />
      ) : null}
    </div>
  );
}
