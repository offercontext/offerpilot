import { ApiOutlined, CopyOutlined, DownloadOutlined, FileSearchOutlined, ReloadOutlined, SettingOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Divider, Empty, Input, Modal, Select, Skeleton, Space, Tag, Typography, message } from 'antd';
import { exportBackup, getLogs, getSettings, getSettingsBackup, type LogEntry, type Settings } from '@/services/chat';
import { ONBOARDING_QUERY_KEY, setOnboardingForceOpen } from '@/services/onboarding';
import { buildDiagnosticsText } from '@/lib/diagnostics';
import { useMemo, useState } from 'react';

interface Props {
  onOpenAISettings: () => void;
}

export default function SettingsView({ onOpenAISettings }: Props) {
  const queryClient = useQueryClient();
  const [logLevel, setLogLevel] = useState('');
  const settingsQuery = useQuery({
    queryKey: ['settings-summary'],
    queryFn: getSettings,
  });
  const logsQuery = useQuery({
    queryKey: ['runtime-logs', 20, logLevel],
    queryFn: () => getLogs(20, logLevel),
    refetchInterval: 15000,
  });
  const reopenOnboardingMutation = useMutation({
    mutationFn: () => setOnboardingForceOpen(true),
    onSuccess: (status) => {
      queryClient.setQueryData(ONBOARDING_QUERY_KEY, status);
      message.success('已重新打开新手引导');
    },
    onError: () => message.error('新手引导打开失败'),
  });
  const backupMutation = useMutation({
    mutationFn: getSettingsBackup,
    onSuccess: (backup) => {
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `offerpilot-settings-backup-v${backup.version}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      message.success('设置备份已导出');
    },
    onError: () => {
      message.error('设置备份导出失败');
    },
  });
  const settings = settingsQuery.data;
  const logs = logsQuery.data ?? [];
  const diagnosticsText = useMemo(
    () => (settings ? buildDiagnosticsText(settings, logs) : ''),
    [settings, logs],
  );

  async function copyDiagnostics() {
    if (!diagnosticsText) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(diagnosticsText);
      message.success('诊断信息已复制');
    } catch {
      Modal.info({
        title: '复制诊断信息失败，请手动复制',
        content: <Input.TextArea value={diagnosticsText} readOnly autoSize={{ minRows: 8, maxRows: 18 }} />,
        width: 720,
      });
    }
  }

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
          设置
        </Typography.Title>
      </div>

      <section style={panelStyle}>
        <Space align="start" size={12}>
          <span style={panelIconStyle}>
            <ApiOutlined />
          </span>
          <div>
            <Typography.Title level={4} style={panelTitleStyle}>
              AI 运行时
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--op-muted)' }}>
              管理模型供应商、模型、密钥与写入确认策略。
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
          <RuntimeField label="运行模式" value={formatRuntimeMode(settings?.runtime_mode)} />
          <RuntimeField label="版本" value={settings?.version ?? '-'} />
          <RuntimeField label="多供应商" value={`${settings?.providers.length ?? 0} 个`} />
          <RuntimeField label="Fallback" value={fallbackLabel(settings)} />
          <RuntimeField label="日志级别" value={settings?.log_level ?? '-'} />
          <RuntimeField label="访问控制" value={settings?.auth_enabled ? '已开启' : '未开启'} />
          <RuntimeField label="密钥状态" value={settings?.has_api_key ? '已配置' : '未配置'} />
          <RuntimeField label="数据目录" value={settings?.data_dir ?? '-'} />
        </div>
        <div>
          <Space wrap>
            <Button type="primary" icon={<SettingOutlined />} onClick={onOpenAISettings}>
              配置 AI
            </Button>
            <Button
              icon={<DownloadOutlined />}
              loading={backupMutation.isPending}
              onClick={() => backupMutation.mutate()}
            >
              导出备份
            </Button>
            <Button icon={<DownloadOutlined />} onClick={() => exportBackup('/backups/export')}>
              导出完整数据
            </Button>
            <Button
              loading={reopenOnboardingMutation.isPending}
              onClick={() => reopenOnboardingMutation.mutate()}
            >
              重新打开新手引导
            </Button>
          </Space>
        </div>
      </section>

      <section style={panelStyle}>
        <Space align="start" size={12}>
          <span style={panelIconStyle}>
            <FileSearchOutlined />
          </span>
          <div style={{ flex: 1 }}>
            <Typography.Title level={4} style={panelTitleStyle}>
              运行诊断
            </Typography.Title>
            <Typography.Text style={{ color: 'var(--op-muted)' }}>
              最近的本地运行日志。
            </Typography.Text>
          </div>
          <Space wrap>
            <Select
              aria-label="日志筛选"
              value={logLevel}
              onChange={setLogLevel}
              options={[
                { value: '', label: '全部日志' },
                { value: 'DEBUG', label: 'DEBUG' },
                { value: 'INFO', label: 'INFO' },
                { value: 'WARNING', label: 'WARNING' },
                { value: 'ERROR', label: 'ERROR' },
              ]}
              style={{ width: 130 }}
            />
            <Button icon={<CopyOutlined />} onClick={copyDiagnostics} disabled={!settings}>
              复制诊断信息
            </Button>
          </Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => logsQuery.refetch()}
            loading={logsQuery.isFetching}
            aria-label="刷新日志"
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
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日志" />;
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

function formatRuntimeMode(value: string | undefined) {
  if (value === 'local') return '本地模式';
  if (value === 'server') return '服务器模式';
  return '-';
}

function fallbackLabel(settings?: Settings) {
  if (!settings?.fallback_provider_ids.length) return '未启用';
  return settings.fallback_provider_ids
    .map((providerId) => settings.providers.find((item) => item.id === providerId)?.label || providerId)
    .join(' → ');
}
