import { useEffect, useState } from 'react';
import { Alert, Empty, List, Spin, Typography } from 'antd';
import { listInterviews } from '@/services/interviews';
import type { InterviewIndexItem } from '@/types/interviewIndex';

const { Paragraph, Title } = Typography;

export default function InterviewV01View() {
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
          查看已安排的面试事件与复盘入口
        </Paragraph>
      </div>
      {loading ? <Spin aria-label="正在加载面试列表" /> : null}
      {error ? <Alert type="error" showIcon message="面试列表暂时无法加载，请稍后重试。" /> : null}
      {!loading && !error && items.length === 0 ? <Empty description="暂无已安排的面试" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      {!loading && !error && items.length > 0 ? (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={`${item.company_name} · ${item.position_name}`}
                description={`${new Date(item.scheduled_at).toLocaleString()}${item.note_id ? ' · 已有复盘' : ' · 待记录复盘'}`}
              />
            </List.Item>
          )}
        />
      ) : null}
    </div>
  );
}
