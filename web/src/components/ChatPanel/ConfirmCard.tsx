import { Card, Button, Space, Typography } from 'antd';
import type { PendingAction } from '@/types/chat';

const { Text } = Typography;

interface Props {
  action: PendingAction;
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmCard({ action, loading, onConfirm, onCancel }: Props) {
  return (
    <Card size="small" style={{ borderColor: '#f59e0b', background: '#fffbeb', margin: '8px 0' }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Text strong>AI 想执行一个修改操作：</Text>
        <Text>{action.human}</Text>
        <Space>
          <Button type="primary" loading={loading} onClick={onConfirm}>
            确认
          </Button>
          <Button disabled={loading} onClick={onCancel}>
            取消
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
