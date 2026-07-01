import type { ViewMode } from '@/layout/AppShell';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

export default function RemindersView(_props: Props) {
  return <div style={{ padding: 24, color: 'var(--op-muted)' }}>提醒中心（待实现）</div>;
}
