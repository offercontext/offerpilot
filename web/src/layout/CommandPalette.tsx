import { useEffect, useMemo, useState } from 'react';
import { Modal, Input, List } from 'antd';
import type { Application } from '@/types/application';
import type { ViewMode } from './AppShell';

export interface Command {
  key: string;
  label: string;
  hint?: string;
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  applications: Application[];
  onNavigate: (v: ViewMode) => void;
  onOpenDetail: (app: Application) => void;
  onAddApplication: () => void;
  onOpenResume: () => void;
  onOpenChat: () => void;
}

export default function CommandPalette({
  open,
  onClose,
  applications,
  onNavigate,
  onOpenDetail,
  onAddApplication,
  onOpenResume,
  onOpenChat,
}: Props) {
  const [q, setQ] = useState('');

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  const actions: Command[] = useMemo(
    () => [
      { key: 'add', label: '添加投递', hint: '动作', run: () => { onAddApplication(); onClose(); } },
      { key: 'resume', label: '简历匹配', hint: '动作', run: () => { onOpenResume(); onClose(); } },
      { key: 'chat', label: '打开 AI 助手', hint: '动作', run: () => { onOpenChat(); onClose(); } },
      { key: 'nav-dashboard', label: '前往 驾驶舱', hint: '导航', run: () => { onNavigate('dashboard'); onClose(); } },
      { key: 'nav-board', label: '前往 看板', hint: '导航', run: () => { onNavigate('board'); onClose(); } },
      { key: 'nav-reminders', label: '前往 提醒', hint: '导航', run: () => { onNavigate('reminders'); onClose(); } },
      { key: 'nav-offers', label: '前往 谈薪', hint: '导航', run: () => { onNavigate('offers'); onClose(); } },
      { key: 'nav-knowledge', label: '前往 知识库', hint: '导航', run: () => { onNavigate('knowledge'); onClose(); } },
    ],
    [onAddApplication, onOpenResume, onOpenChat, onNavigate, onClose]
  );

  const kw = q.trim().toLowerCase();
  const appMatches: Command[] = kw
    ? applications
        .filter(
          (a) =>
            a.company_name.toLowerCase().includes(kw) ||
            a.position_name.toLowerCase().includes(kw)
        )
        .slice(0, 6)
        .map((a) => ({
          key: `app-${a.id}`,
          label: `${a.company_name} · ${a.position_name}`,
          hint: '投递',
          run: () => { onOpenDetail(a); onClose(); },
        }))
    : [];

  const actionMatches = kw
    ? actions.filter((c) => c.label.toLowerCase().includes(kw))
    : actions;

  const items = [...appMatches, ...actionMatches];

  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} width={520} styles={{ body: { padding: 0 } }}>
      <Input
        autoFocus
        size="large"
        variant="borderless"
        placeholder="搜索投递、跳转页面、执行动作…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ padding: '14px 16px' }}
      />
      <div style={{ maxHeight: 360, overflowY: 'auto', borderTop: '1px solid var(--op-border)' }}>
        <List
          dataSource={items}
          locale={{ emptyText: '无匹配结果' }}
          renderItem={(c) => (
            <List.Item
              onClick={c.run}
              style={{ padding: '10px 16px', cursor: 'pointer' }}
            >
              <span style={{ color: 'var(--op-ink)' }}>{c.label}</span>
              {c.hint && <span style={{ fontSize: 11, color: 'var(--op-muted)' }}>{c.hint}</span>}
            </List.Item>
          )}
        />
      </div>
    </Modal>
  );
}
