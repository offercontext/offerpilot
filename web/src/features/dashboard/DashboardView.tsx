import type { ViewMode } from '@/layout/AppShell';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

export default function DashboardView(_props: Props) {
  return <div style={{ padding: 24, color: 'var(--op-muted)' }}>驾驶舱（待实现）</div>;
}
