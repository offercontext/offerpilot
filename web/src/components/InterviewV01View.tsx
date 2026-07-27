import { useEffect, useState } from 'react';
import { Alert, Button, Empty, List, Space, Spin, Tag, Typography } from 'antd';
import { listInterviews } from '@/services/interviews';
import type { InterviewIndexItem } from '@/types/interviewIndex';

const { Paragraph, Title } = Typography;

interface Props {
  onOpenApplication?: (applicationId: number) => void;
}

export default function InterviewV01View({ onOpenApplication }: Props) {
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
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>面试</Title>
        <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
          查看已安排的面试事件、复盘、证据化建议和准备入口。
        </Paragraph>
      </div>
      {loading ? <Spin aria-label="正在加载面试列表" /> : null}
      {error ? <Alert type="error" showIcon message="面试列表暂时无法加载，请稍后重试。" /> : null}
      {!loading && !error && items.length === 0 ? <Empty description="暂无已安排的面试" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      {!loading && !error && items.length > 0 ? (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item actions={[
              <Button key="detail" type="link" onClick={() => onOpenApplication?.(item.application_id)}>
                查看投递详情
              </Button>,
              item.preparation_available ? (
                <Button key="prepare" type="link" onClick={() => onOpenApplication?.(item.application_id)}>
                  准备面试
                </Button>
              ) : null,
            ]}>
              <List.Item.Meta
                title={`${item.company_name} · ${item.position_name}`}
                description={(
                  <Space wrap>
                    <span>{new Date(item.scheduled_at).toLocaleString()}</span>
                    <Tag>{item.note_id ? '已有复盘' : '待记录复盘'}</Tag>
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
