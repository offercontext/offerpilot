import { useEffect, useMemo, useState } from 'react';
import { Modal, Input, List } from 'antd';
import type { Application } from '@/types/application';
import type { PipelineInsight } from '@/lib/pipelineInsights';
import { MODULE_NAV, type ViewMode } from './navigation';

export interface Command {
  key: string;
  label: string;
  hint?: string;
  run: () => void;
}

function pipelineInsightMatches(item: PipelineInsight, keyword: string): boolean {
  if (!keyword) return true;

  const hint = `流程提醒 - ${item.priority.toUpperCase()}`;
  return [
    item.title,
    hint,
    item.kind,
    item.reason,
    item.primaryAction.label,
    ...item.evidence,
  ]
    .join(' ')
    .toLowerCase()
    .includes(keyword);
}

interface Props {
  open: boolean;
  onClose: () => void;
  applications: Application[];
  onNavigate: (v: ViewMode) => void;
  onOpenDetail: (app: Application) => void;
  onAddApplication: () => void;
  onOpenResume: () => void;
  onUploadResume?: () => void;
  onOpenChat: () => void;
  onOpenSettings: () => void;
  pipelineActions: PipelineInsight[];
  onRunPipelineAction: (item: PipelineInsight) => void;
}

export default function CommandPalette({
  open,
  onClose,
  applications,
  onNavigate,
  onOpenDetail,
  onAddApplication,
  onOpenResume,
  onUploadResume,
  onOpenChat,
  onOpenSettings,
  pipelineActions,
  onRunPipelineAction,
}: Props) {
  const [q, setQ] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [open, q]);

  const actions: Command[] = useMemo(
    () => [
      { key: 'add', label: '添加投递', hint: '动作', run: () => { onAddApplication(); onClose(); } },
      { key: 'resume-library', label: '打开简历库', hint: '简历', run: () => { onOpenResume(); onClose(); } },
      { key: 'new-resume', label: '新建简历', hint: '在简历库创建薄版', run: () => { onOpenResume(); onClose(); } },
      { key: 'uploadResume', label: '上传简历', hint: 'PDF 到简历库', run: () => { onUploadResume?.(); onClose(); } },
      { key: 'chat', label: '打开 Pilot', hint: '动作', run: () => { onOpenChat(); onClose(); } },
      { key: 'settings-ai', label: '打开 AI 设置', hint: '设置', run: () => { onOpenSettings(); onClose(); } },
      ...MODULE_NAV.map((item) => ({
        key: `nav-${item.key}`,
        label: `前往 ${item.label}`,
        hint: '导航',
        run: () => {
          onNavigate(item.defaultView);
          onClose();
        },
      })),
    ],
    [onAddApplication, onOpenResume, onUploadResume, onOpenChat, onOpenSettings, onNavigate, onClose]
  );

  const kw = q.trim().toLowerCase();
  const pipelineCommands: Command[] = useMemo(
    () =>
      pipelineActions
        .filter((item) => pipelineInsightMatches(item, kw))
        .slice(0, 5)
        .map((item) => ({
          key: `pipeline-${item.id}`,
          label: item.title,
          hint: `流程提醒 - ${item.priority.toUpperCase()}`,
          run: () => {
            onRunPipelineAction(item);
            onClose();
          },
        })),
    [pipelineActions, kw, onRunPipelineAction, onClose]
  );
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

  const items = [...appMatches, ...pipelineCommands, ...actionMatches];

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      items[activeIndex]?.run();
    }
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} closable={false} width={520} styles={{ body: { padding: 0 } }}>
      <Input
        autoFocus
        size="large"
        variant="borderless"
        placeholder="搜索投递、跳转页面、执行动作…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKeyDown}
        style={{ padding: '14px 16px' }}
      />
      <div style={{ maxHeight: 360, overflowY: 'auto', borderTop: '1px solid var(--op-border)' }}>
        <List
          dataSource={items}
          locale={{ emptyText: '无匹配结果' }}
          renderItem={(c, index) => (
            <List.Item
              onClick={c.run}
              onMouseEnter={() => setActiveIndex(index)}
              style={{
                padding: '10px 16px',
                cursor: 'pointer',
                background: index === activeIndex ? 'var(--op-layout-bg)' : undefined,
              }}
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
