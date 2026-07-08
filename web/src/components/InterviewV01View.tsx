import { useState } from 'react';
import { App as AntApp, Button, Empty, Input, Space, Typography } from 'antd';
import { SaveOutlined } from '@ant-design/icons';

const { Paragraph, Title } = Typography;

export default function InterviewV01View() {
  const [draft, setDraft] = useState('');
  const { message } = AntApp.useApp();

  function saveDraft() {
    message.info('操作完成');
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>
          面试
        </Title>
        <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
          暂无面试记录
        </Paragraph>
      </div>

      <Empty description="暂无面试记录" image={Empty.PRESENTED_IMAGE_SIMPLE}>
        <Space direction="vertical" size={12} style={{ width: 'min(560px, 100%)' }}>
          <Input.TextArea
            rows={4}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="临时备注"
          />
          <Button type="primary" icon={<SaveOutlined />} onClick={saveDraft}>
            保存
          </Button>
        </Space>
      </Empty>
    </div>
  );
}
