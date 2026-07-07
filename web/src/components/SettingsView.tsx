import { ApiOutlined, FileSearchOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { Button, Divider, Empty, Skeleton, Space, Tag, Typography } from 'antd';
import { getLogs, getSettings, type LogEntry } from '@/services/chat';

interface Props {
  onOpenAISettings: () => void;
}

export default function SettingsView({ onOpenAISettings }: Props) {
  const settingsQuery = useQuery({
    queryKey: ['settings-summary'],
    queryFn: getSettings,
  });
  const logsQuery = useQuery({
    queryKey: ['runtime-logs', 20],
    queryFn: () => getLogs(20),
    refetchInterval: 15000,
  });
  const settings = settingsQuery.data;
  const logs = logsQuery.data ?? [];

  return (
    <section
      style={{
        maxWidth: 1040,
        display: 'grid',
        gap: 20,
      }}
    >
      <div>
        <Typography.Title level={2} style={{ margin: 0, color: 'var(--op-ink)' }}>
          Settings
        </Typography.Title>
      </div>

      <section style={panelStyle}>
        <Space align="start" size={12}>
          <span style={panelIconStyle}>
            <ApiOutlined />
          </span>
          <div>
            <Typography.Title level={4} style={panelTitleStyle}>
              AI runtime
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--op-muted)' }}>
              Provider, model, API key, and write confirmation policy
            </Typography.Text>
          </div>
        </Space>
        <Divider style={{ margin: 0 }} />
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
            gap: 12,
          }}
        >
          <RuntimeField label="Mode" value={settings?.runtime_mode ?? '-'} />
          <RuntimeField label="Log level" value={settings?.log_level ?? '-'} />
          <RuntimeField label="Auth" value={settings?.auth_enabled ? 'enabled' : 'disabled'} />
          <RuntimeField label="API key" value={settings?.has_api_key ? 'set' : 'missing'} />
        </div>
        <div>
          <Button type="primary" icon={<SettingOutlined />} onClick={onOpenAISettings}>
            Configure AI
          </Button>
        </div>
      </section>

      <section style={panelStyle}>
        <Space align="start" size={12}>
          <span style={panelIconStyle}>
            <FileSearchOutlined />
          </span>
          <div style={{ flex: 1 }}>
            <Typography.Title level={4} style={panelTitleStyle}>
              Runtime diagnostics
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--op-muted)' }}>
              Recent local runtime log entries
            </Typography.Text>
          </div>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => logsQuery.refetch()}
            loading={logsQuery.isFetching}
            aria-label="Refresh logs"
          />
        </Space>
        <Divider style={{ margin: 0 }} />
        {logsQuery.isLoading ? <Skeleton active paragraph={{ rows: 3 }} /> : <LogList entries={logs} />}
      </section>
    </section>
  );
}

const panelStyle = {
  display: 'grid',
  gap: 16,
  padding: 20,
  background: 'var(--op-surface)',
  border: '1px solid var(--op-border)',
  borderRadius: 8,
  boxShadow: 'var(--op-shadow-sm)',
} as const;

const panelIconStyle = {
  color: 'var(--op-primary)',
  fontSize: 20,
  lineHeight: 1,
} as const;

const panelTitleStyle = {
  margin: 0,
  color: 'var(--op-ink)',
  textWrap: 'balance',
} as const;

function RuntimeField({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        minHeight: 64,
        padding: 12,
        borderRadius: 6,
        background: 'rgba(148, 163, 184, 0.08)',
      }}
    >
      <Typography.Text style={{ display: 'block', color: 'var(--op-muted)', fontSize: 12 }}>
        {label}
      </Typography.Text>
      <Typography.Text strong style={{ color: 'var(--op-ink)', fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </Typography.Text>
    </div>
  );
}

function LogList({ entries }: { entries: LogEntry[] }) {
  if (!entries.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No logs yet" />;
  }
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {entries.map((entry, index) => (
        <div
          key={`${entry.level}-${index}-${entry.message}`}
          style={{
            display: 'grid',
            gridTemplateColumns: '88px minmax(0, 1fr)',
            gap: 10,
            alignItems: 'start',
            padding: '10px 12px',
            borderRadius: 6,
            background: 'rgba(15, 23, 42, 0.03)',
          }}
        >
          <Tag color={levelColor(entry.level)} style={{ margin: 0, textAlign: 'center' }}>
            {entry.level || 'INFO'}
          </Tag>
          <Typography.Text style={{ color: 'var(--op-ink)', overflowWrap: 'anywhere' }}>
            {entry.message || '-'}
          </Typography.Text>
        </div>
      ))}
    </div>
  );
}

function levelColor(level: string) {
  switch (level.toUpperCase()) {
    case 'DEBUG':
      return 'default';
    case 'WARNING':
      return 'gold';
    case 'ERROR':
      return 'red';
    default:
      return 'blue';
  }
}
