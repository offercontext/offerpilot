import { ApiOutlined, SettingOutlined } from '@ant-design/icons';
import { Button, Divider, Space, Typography } from 'antd';

interface Props {
  onOpenAISettings: () => void;
}

export default function SettingsView({ onOpenAISettings }: Props) {
  return (
    <section
      style={{
        maxWidth: 920,
        display: 'grid',
        gap: 20,
      }}
    >
      <div>
        <Typography.Title level={2} style={{ margin: 0, color: 'var(--op-ink)' }}>
          设置
        </Typography.Title>
      </div>

      <div
        style={{
          display: 'grid',
          gap: 16,
          padding: 20,
          background: 'var(--op-surface)',
          border: '1px solid var(--op-border)',
          borderRadius: 8,
          boxShadow: 'var(--op-shadow-sm)',
        }}
      >
        <Space align="start" size={12}>
          <span style={{ color: 'var(--op-primary)', fontSize: 20, lineHeight: 1 }}>
            <ApiOutlined />
          </span>
          <div>
            <Typography.Title level={4} style={{ margin: 0, color: 'var(--op-ink)' }}>
              AI 运行时
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--op-muted)' }}>
              模型提供商、Base URL、API Key、温度和超时
            </Typography.Text>
          </div>
        </Space>
        <Divider style={{ margin: 0 }} />
        <div>
          <Button type="primary" icon={<SettingOutlined />} onClick={onOpenAISettings}>
            配置 AI
          </Button>
        </div>
      </div>
    </section>
  );
}
