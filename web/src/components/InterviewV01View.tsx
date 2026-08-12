import { useEffect, useState } from 'react';
import { Alert, Button, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import { listInterviews } from '@/services/interviews';
import type { InterviewIndexItem } from '@/types/interviewIndex';
import workflowStyles from './ui/WorkflowSurface.module.css';

const { Paragraph, Title } = Typography;

interface Props {
  onOpenApplication?: (applicationId: number) => void;
  onOpenPreparation?: (applicationId: number, eventId: number) => void;
  onOpenMockInterview?: (applicationId: number, eventId: number) => void;
  onOpenStoryLibrary?: (reviewNoteId?: number) => void;
}

export default function InterviewV01View({ onOpenApplication, onOpenPreparation, onOpenMockInterview, onOpenStoryLibrary }: Props) {
  const [items, setItems] = useState<InterviewIndexItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

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
