import {
  DashboardOutlined,
  AppstoreOutlined,
  CalendarOutlined,
  BellOutlined,
  FileSearchOutlined,
  DollarOutlined,
  BookOutlined,
  ReadOutlined,
  RobotOutlined,
  BulbOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { Badge } from 'antd';
import { useThemeMode } from '@/theme/ThemeContext';
import type { ViewMode } from './AppShell';

const NAV: { key: ViewMode; label: string; icon: React.ReactNode }[] = [
  { key: 'dashboard', label: '驾驶舱', icon: <DashboardOutlined /> },
  { key: 'board', label: '看板', icon: <AppstoreOutlined /> },
  { key: 'calendar', label: '日历', icon: <CalendarOutlined /> },
  { key: 'reminders', label: '提醒', icon: <BellOutlined /> },
  { key: 'reviews', label: '复盘', icon: <FileSearchOutlined /> },
  { key: 'offers', label: '谈薪', icon: <DollarOutlined /> },
  { key: 'knowledge', label: '知识库', icon: <BookOutlined /> },
  { key: 'questions', label: '题库刷题', icon: <ReadOutlined /> },
  { key: 'resumes', label: '简历库', icon: <FileTextOutlined /> },
];

interface Props {
  view: ViewMode;
  onChange: (v: ViewMode) => void;
  reminderCount: number;
  onOpenChat: () => void;
}

export default function Sidebar({ view, onChange, reminderCount, onOpenChat }: Props) {
  const { mode, toggle } = useThemeMode();
  return (
    <nav
      aria-label="主导航"
      style={{
        width: 200,
        flexShrink: 0,
        background: 'var(--op-surface)',
        borderRight: '1px solid var(--op-border)',
        padding: '16px 12px',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px 18px' }}>
        <span
          style={{
            width: 26,
            height: 26,
            borderRadius: 9,
            background: 'var(--op-gradient-brand)',
            display: 'inline-block',
          }}
        />
        <span className="op-gradient-text" style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.02em' }}>
          OfferPilot
        </span>
      </div>

      {NAV.map((item) => {
        const active = view === item.key;
        return (
          <button
            key={item.key}
            aria-current={active ? 'page' : undefined}
            onClick={() => onChange(item.key)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '9px 11px',
              border: 'none',
              cursor: 'pointer',
              borderRadius: 11,
              fontSize: 14,
              textAlign: 'left',
              fontWeight: active ? 600 : 400,
              color: active ? 'var(--op-primary)' : 'var(--op-muted)',
              background: active ? 'var(--op-layout-bg)' : 'transparent',
              boxShadow: active ? 'var(--op-shadow-sm)' : 'none',
              transition: 'background 0.2s var(--op-ease)',
            }}
          >
            <span style={{ fontSize: 16, display: 'inline-flex' }}>{item.icon}</span>
            <span style={{ flex: 1 }}>{item.label}</span>
            {item.key === 'reminders' && reminderCount > 0 && (
              <Badge count={reminderCount} size="small" />
            )}
          </button>
        );
      })}

      <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button
          onClick={onOpenChat}
          style={{
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            background: 'var(--op-layout-bg)',
            borderRadius: 12,
            padding: 11,
            color: 'var(--op-primary)',
            fontSize: 13,
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <RobotOutlined /> AI 助手
        </button>
        <button
          onClick={toggle}
          aria-label="切换明暗模式"
          style={{
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            background: 'transparent',
            borderRadius: 12,
            padding: '9px 11px',
            color: 'var(--op-muted)',
            fontSize: 13,
            display: 'flex',
            gap: 8,
            alignItems: 'center',
          }}
        >
          <BulbOutlined /> {mode === 'dark' ? '亮色模式' : '暗色模式'}
        </button>
      </div>
    </nav>
  );
}
