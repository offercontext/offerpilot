# OfferPilot 前端重构实施计划：高级柔和视觉系统 + 求职驾驶舱 + 提醒中心

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OfferPilot 从默认 AntD 外观重构为「高级柔和」设计系统，用持久侧边栏取代 Segmented 导航，并新增求职驾驶舱主页与提醒中心。

**Architecture:** 纯前端改造。新建 `theme/`（AntD 主题 token + CSS 变量 + 明暗上下文）、`layout/`（AppShell/Sidebar/TopBar/CommandPalette）、`features/dashboard` 与 `features/reminders`，以及纯函数模块 `lib/insights.ts`（从现有 applications/events/offers 派生 KPI、漏斗、动量、提醒）。现有视图组件复用，仅做视觉对齐。不改后端、不加路由/图表/测试框架。

**Tech Stack:** React 18 + TypeScript + Vite + Ant Design 5 + TanStack Query + dayjs（均为现有依赖）。

**验证方式：** 项目无测试框架。每个任务以 `cd web && npx tsc -b`（类型检查通过）作为验证，最后 `npm run build` + 手动走查。所有路径相对仓库根。工作目录为 worktree `.worktrees/feat-ui-redesign`。

**字体决策：** 不自托管 woff2（离线 + 无二进制资产）；用系统字体栈 + tabular-nums + 展示字紧字距达成质感。

---

## 文件结构总览

```
web/src/
  theme/
    tokens.css        # 新建：CSS 变量（渐变/阴影/缓动/间距/字体栈）
    antdTheme.ts      # 新建：light/dark ConfigProvider theme 对象
    ThemeContext.tsx  # 新建：明暗模式 + localStorage 持久化
  lib/
    insights.ts       # 新建：纯函数（KPI/漏斗/动量/提醒派生）
  layout/
    AppShell.tsx      # 新建：侧边栏+顶栏+内容区+全局 Modal 编排
    Sidebar.tsx       # 新建
    TopBar.tsx        # 新建
    CommandPalette.tsx# 新建：⌘K
  features/
    dashboard/
      DashboardView.tsx        # 新建
      widgets/KpiCards.tsx     # 新建
      widgets/ConversionFunnel.tsx  # 新建
      widgets/RemindersSummary.tsx  # 新建
      widgets/MomentumChart.tsx     # 新建
      widgets/UpcomingSchedule.tsx  # 新建
      dashboard.module.css     # 新建
    reminders/
      RemindersView.tsx        # 新建
      reminders.module.css     # 新建
  main.tsx            # 改：接入 ThemeProvider + 主题
  App.tsx             # 改：精简为渲染 AppShell
  components/KanbanBoard/KanbanBoard.module.css  # 改：柔和调板
  services/offers.ts  # 读：确认 listOffers 名称
```

---

## Task 1: 设计 token（CSS 变量 + AntD 主题）

**Files:**
- Create: `web/src/theme/tokens.css`
- Create: `web/src/theme/antdTheme.ts`

- [ ] **Step 1: 创建 CSS 变量文件**

Create `web/src/theme/tokens.css`:

```css
:root {
  /* 品牌色 */
  --op-primary: #6366f1;
  --op-accent: #a855f7;
  --op-success: #059669;
  --op-warning: #d97706;
  --op-error: #ef4444;
  --op-ink: #23213a;
  --op-muted: #8b87b3;
  --op-layout-bg: #f6f6fb;
  --op-surface: #ffffff;
  --op-border: #ecebf5;

  /* 渐变 */
  --op-gradient-brand: linear-gradient(135deg, #6366f1, #a855f7);

  /* 阴影（柔和彩色低透明度） */
  --op-shadow-sm: 0 1px 4px rgba(31, 29, 58, 0.05);
  --op-shadow-md: 0 2px 10px rgba(99, 102, 241, 0.08);
  --op-shadow-lg: 0 8px 28px rgba(99, 102, 241, 0.14);

  /* 缓动 */
  --op-ease: cubic-bezier(0.22, 1, 0.36, 1);

  /* 字体栈（离线系统栈） */
  --op-font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "HarmonyOS Sans SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
}

:root[data-theme="dark"] {
  --op-ink: #e7e5f2;
  --op-muted: #9a95bf;
  --op-layout-bg: #141322;
  --op-surface: #1c1a2e;
  --op-border: #2a2740;
  --op-shadow-sm: 0 1px 4px rgba(0, 0, 0, 0.3);
  --op-shadow-md: 0 2px 12px rgba(0, 0, 0, 0.35);
  --op-shadow-lg: 0 8px 30px rgba(0, 0, 0, 0.45);
}

html, body, #root { height: 100%; }
body {
  margin: 0;
  font-family: var(--op-font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background: var(--op-layout-bg);
}

/* 数字对齐 */
.op-tnum { font-variant-numeric: tabular-nums; }

/* 品牌渐变文字 */
.op-gradient-text {
  background: var(--op-gradient-brand);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

/* 视图切换入场 */
.op-view-enter { animation: opViewIn 0.22s var(--op-ease); }
@keyframes opViewIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .op-view-enter { animation: none; }
  * { scroll-behavior: auto !important; }
}
```

- [ ] **Step 2: 创建 AntD 主题对象**

Create `web/src/theme/antdTheme.ts`:

```ts
import { theme as antdAlgorithms, type ThemeConfig } from 'antd';

const sharedFont =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif';

const sharedToken = {
  colorPrimary: '#6366f1',
  colorSuccess: '#059669',
  colorWarning: '#d97706',
  colorError: '#ef4444',
  colorInfo: '#6366f1',
  borderRadius: 12,
  fontFamily: sharedFont,
  fontSize: 14,
};

export const lightTheme: ThemeConfig = {
  algorithm: antdAlgorithms.defaultAlgorithm,
  token: {
    ...sharedToken,
    colorBgLayout: '#f6f6fb',
    colorBgContainer: '#ffffff',
    colorText: '#23213a',
    colorTextSecondary: '#8b87b3',
    colorBorderSecondary: '#ecebf5',
    boxShadow: '0 2px 10px rgba(99,102,241,0.08)',
    boxShadowSecondary: '0 8px 28px rgba(99,102,241,0.14)',
  },
  components: {
    Button: { primaryShadow: '0 4px 12px rgba(99,102,241,0.30)', controlHeight: 36 },
    Card: { borderRadiusLG: 14 },
    Modal: { borderRadiusLG: 16 },
    Segmented: { borderRadius: 10 },
  },
};

export const darkTheme: ThemeConfig = {
  algorithm: antdAlgorithms.darkAlgorithm,
  token: {
    ...sharedToken,
    colorBgLayout: '#141322',
    colorBgContainer: '#1c1a2e',
    colorText: '#e7e5f2',
    colorTextSecondary: '#9a95bf',
    colorBorderSecondary: '#2a2740',
  },
  components: {
    Button: { controlHeight: 36 },
    Card: { borderRadiusLG: 14 },
    Modal: { borderRadiusLG: 16 },
  },
};
```

- [ ] **Step 3: 类型检查**

Run: `cd web && npx tsc -b`
Expected: PASS（无类型错误；tokens.css 未被引用不影响编译）

- [ ] **Step 4: 提交**

```bash
git add web/src/theme/tokens.css web/src/theme/antdTheme.ts
git commit -m "feat(theme): soft-premium design tokens and antd theme"
```

---

## Task 2: 明暗主题上下文 + main.tsx 接入

**Files:**
- Create: `web/src/theme/ThemeContext.tsx`
- Modify: `web/src/main.tsx`

- [ ] **Step 1: 创建 ThemeContext**

Create `web/src/theme/ThemeContext.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

type Mode = 'light' | 'dark';
interface ThemeCtx {
  mode: Mode;
  toggle: () => void;
}

const Ctx = createContext<ThemeCtx>({ mode: 'light', toggle: () => {} });
const STORAGE_KEY = 'op-theme';

function initialMode(): Mode {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(initialMode);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
    localStorage.setItem(STORAGE_KEY, mode);
  }, [mode]);

  const toggle = () => setMode((m) => (m === 'light' ? 'dark' : 'light'));
  return <Ctx.Provider value={{ mode, toggle }}>{children}</Ctx.Provider>;
}

export function useThemeMode() {
  return useContext(Ctx);
}
```

- [ ] **Step 2: 改写 main.tsx 接入主题**

Replace the full content of `web/src/main.tsx` with:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import { ThemeProvider, useThemeMode } from './theme/ThemeContext';
import { lightTheme, darkTheme } from './theme/antdTheme';
import './theme/tokens.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

function ThemedApp() {
  const { mode } = useThemeMode();
  return (
    <ConfigProvider locale={zhCN} theme={mode === 'dark' ? darkTheme : lightTheme}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ThemedApp />
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>
);
```

- [ ] **Step 3: 类型检查**

Run: `cd web && npx tsc -b`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add web/src/theme/ThemeContext.tsx web/src/main.tsx
git commit -m "feat(theme): light/dark mode context wired into providers"
```

---

## Task 3: insights.ts 纯函数（派生逻辑核心）

**Files:**
- Create: `web/src/lib/insights.ts`
- Read for reference: `web/src/types/application.ts`, `web/src/types/event.ts`, `web/src/types/offer.ts`

- [ ] **Step 1: 确认 offers 服务导出名**

Run: `grep -n "export async function" web/src/services/offers.ts`
Expected: 找到列表函数名（如 `listOffers`）。若不同，Task 7 中据实替换。

- [ ] **Step 2: 编写 insights.ts**

Create `web/src/lib/insights.ts`:

```ts
import dayjs from 'dayjs';
import type { Application, ApplicationStatus } from '@/types/application';
import type { ScheduleEvent } from '@/types/event';
import type { Offer } from '@/types/offer';

export interface Kpis {
  total: number;
  interviewing: number;
  offers: number;
  responseRate: number; // 0..1
  weeklyDelta: number; // 近 7 天新增投递数
}

export interface FunnelStage {
  key: string;
  label: string;
  count: number;
  ratio: number; // 相对总投递
}

export interface MomentumBucket {
  label: string; // 如 "6/23"
  count: number;
}

export type ReminderSeverity = 'red' | 'amber' | 'green';
export type ReminderKind = 'stale' | 'interview' | 'offer_deadline' | 'no_next';
export type ReminderTarget = 'board' | 'calendar' | 'offers';

export interface Reminder {
  id: string;
  kind: ReminderKind;
  severity: ReminderSeverity;
  title: string;
  detail: string;
  appId?: number;
  offerId?: number;
  eventId?: number;
  target: ReminderTarget;
  sortKey: number; // 越小越紧急
}

// 阈值（集中管理，便于将来做成设置）
export const STALE_DAYS = 7;
export const STALE_RED_DAYS = 14;
export const INTERVIEW_SOON_HOURS = 72;
export const OFFER_SOON_DAYS = 7;

// 表示"已收到回音"的状态（eliminated 视为无回音/静默）
const RESPONDED: ApplicationStatus[] = [
  'assessment',
  'written_test',
  'interview',
  'offer',
  'rejected',
];
// 仍在等待对方回复的状态（用于停滞检测）
const WAITING: ApplicationStatus[] = ['applied', 'assessment', 'written_test'];

export function computeKpis(apps: Application[], now = dayjs()): Kpis {
  const total = apps.length;
  const interviewing = apps.filter((a) => a.status === 'interview').length;
  const offers = apps.filter((a) => a.status === 'offer').length;
  const responded = apps.filter((a) => RESPONDED.includes(a.status)).length;
  const weeklyDelta = apps.filter(
    (a) => a.applied_at && now.diff(dayjs(a.applied_at), 'day') < 7
  ).length;
  return {
    total,
    interviewing,
    offers,
    responseRate: total === 0 ? 0 : responded / total,
    weeklyDelta,
  };
}

export function computeFunnel(apps: Application[]): FunnelStage[] {
  const total = apps.length;
  const inScreen = apps.filter((a) =>
    ['assessment', 'written_test', 'interview', 'offer'].includes(a.status)
  ).length;
  const inInterview = apps.filter((a) => ['interview', 'offer'].includes(a.status)).length;
  const inOffer = apps.filter((a) => a.status === 'offer').length;
  const ratio = (n: number) => (total === 0 ? 0 : n / total);
  return [
    { key: 'applied', label: '投递', count: total, ratio: 1 },
    { key: 'screen', label: '初筛', count: inScreen, ratio: ratio(inScreen) },
    { key: 'interview', label: '面试', count: inInterview, ratio: ratio(inInterview) },
    { key: 'offer', label: 'Offer', count: inOffer, ratio: ratio(inOffer) },
  ];
}

export function computeMomentum(apps: Application[], weeks = 4, now = dayjs()): MomentumBucket[] {
  const buckets: MomentumBucket[] = [];
  for (let i = weeks - 1; i >= 0; i--) {
    const start = now.subtract(i, 'week').startOf('week');
    const end = start.add(1, 'week');
    const count = apps.filter((a) => {
      if (!a.applied_at) return false;
      const d = dayjs(a.applied_at);
      return (d.isAfter(start) || d.isSame(start)) && d.isBefore(end);
    }).length;
    buckets.push({ label: start.format('M/D'), count });
  }
  return buckets;
}

export function deriveReminders(
  apps: Application[],
  events: ScheduleEvent[],
  offers: Offer[],
  now = dayjs()
): Reminder[] {
  const out: Reminder[] = [];

  // 1. 投递停滞
  for (const a of apps) {
    if (!WAITING.includes(a.status)) continue;
    const base = a.updated_at || a.applied_at;
    if (!base) continue;
    const days = now.diff(dayjs(base), 'day');
    if (days <= STALE_DAYS) continue;
    out.push({
      id: `stale-${a.id}`,
      kind: 'stale',
      severity: days >= STALE_RED_DAYS ? 'red' : 'amber',
      title: `${a.company_name} · ${a.position_name}`,
      detail: `已投 ${days} 天无回音，建议跟进`,
      appId: a.id,
      target: 'board',
      sortKey: 10000 - days, // 停滞越久越靠前
    });
  }

  // 2. 面试倒计时
  for (const e of events) {
    if (!e.scheduled_at) continue;
    const when = dayjs(e.scheduled_at);
    const hours = when.diff(now, 'hour', true);
    if (hours < 0 || hours > INTERVIEW_SOON_HOURS) continue;
    const label = e.company_name ? `${e.company_name} · ${e.position_name ?? ''}` : '面试安排';
    out.push({
      id: `event-${e.id}`,
      kind: 'interview',
      severity: hours < 24 ? 'red' : 'amber',
      title: label.trim(),
      detail: `${when.format('M月D日 HH:mm')} 面试，去准备`,
      appId: e.application_id,
      eventId: e.id,
      target: 'calendar',
      sortKey: hours,
    });
  }

  // 3. Offer 答复期
  for (const o of offers) {
    if (!['pending', 'negotiating'].includes(o.status)) continue;
    if (!o.deadline) continue;
    const dl = dayjs(o.deadline);
    const days = dl.diff(now, 'day');
    if (days < 0 || days > OFFER_SOON_DAYS) continue;
    out.push({
      id: `offer-${o.id}`,
      kind: 'offer_deadline',
      severity: days <= 2 ? 'red' : 'amber',
      title: `${o.company_name} Offer`,
      detail: `还剩 ${days} 天答复期`,
      offerId: o.id,
      appId: o.application_id,
      target: 'offers',
      sortKey: days,
    });
  }

  // 4. 面试中但无未来安排
  const appsWithFutureEvent = new Set(
    events
      .filter((e) => e.scheduled_at && dayjs(e.scheduled_at).isAfter(now))
      .map((e) => e.application_id)
  );
  for (const a of apps) {
    if (a.status !== 'interview' || appsWithFutureEvent.has(a.id)) continue;
    out.push({
      id: `nonext-${a.id}`,
      kind: 'no_next',
      severity: 'amber',
      title: `${a.company_name} · ${a.position_name}`,
      detail: '面试进行中，未安排下一场',
      appId: a.id,
      target: 'calendar',
      sortKey: 5000,
    });
  }

  const rank: Record<ReminderSeverity, number> = { red: 0, amber: 1, green: 2 };
  return out.sort((x, y) => rank[x.severity] - rank[y.severity] || x.sortKey - y.sortKey);
}

export function reminderBadgeCount(reminders: Reminder[]): number {
  return reminders.filter((r) => r.severity === 'red' || r.severity === 'amber').length;
}
```

- [ ] **Step 3: 类型检查**

Run: `cd web && npx tsc -b`
Expected: PASS。若报 dayjs `isAfter/isSame/isBefore` 类型问题，说明 dayjs 已内置，无需插件；若报 `diff` 第三参 `true` 类型，改为 `when.diff(now, 'hour')`（整数小时）并相应放宽判断。

- [ ] **Step 4: 手动逻辑核对（无测试框架）**

阅读 `deriveReminders` 一遍，确认：停滞仅覆盖 WAITING 状态；面试窗口 0–72h；Offer 0–7 天；排序 red→amber→green。记录在提交信息中。

- [ ] **Step 5: 提交**

```bash
git add web/src/lib/insights.ts
git commit -m "feat(insights): pure derivations for kpis, funnel, momentum, reminders"
```

---

## Task 4: 应用外壳（Sidebar + TopBar + AppShell 骨架）

**Files:**
- Create: `web/src/layout/Sidebar.tsx`
- Create: `web/src/layout/TopBar.tsx`
- Create: `web/src/layout/AppShell.tsx`

本任务先搭外壳并挂载现有 7 个视图（含新页占位），命令面板在 Task 8 补。

- [ ] **Step 1: 定义共享视图类型（放在 AppShell 中导出）+ Sidebar**

Create `web/src/layout/Sidebar.tsx`:

```tsx
import {
  DashboardOutlined,
  AppstoreOutlined,
  CalendarOutlined,
  BellOutlined,
  FileSearchOutlined,
  DollarOutlined,
  BookOutlined,
  RobotOutlined,
  BulbOutlined,
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
```

- [ ] **Step 2: TopBar**

Create `web/src/layout/TopBar.tsx`:

```tsx
import { Button } from 'antd';
import { PlusOutlined, SearchOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';

interface Props {
  streakDays: number;
  onAdd: () => void;
  onSearch: () => void;
}

function greeting(): string {
  const h = dayjs().hour();
  if (h < 6) return '夜深了，注意休息';
  if (h < 12) return '早上好，继续加油';
  if (h < 18) return '下午好，保持节奏';
  return '晚上好，今天辛苦了';
}

export default function TopBar({ streakDays, onAdd, onSearch }: Props) {
  return (
    <header
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '18px 24px',
      }}
    >
      <div>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--op-ink)', letterSpacing: '-0.02em' }}>
          {greeting()} 👋
        </div>
        <div style={{ fontSize: 12, color: 'var(--op-muted)', marginTop: 2 }}>
          {dayjs().format('YYYY 年 M 月 D 日')}
          {streakDays > 0 && ` · 已连续投递 ${streakDays} 天`}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Button icon={<SearchOutlined />} onClick={onSearch}>
          搜索 <span style={{ opacity: 0.6, marginLeft: 4 }}>⌘K</span>
        </Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={onAdd}>
          添加投递
        </Button>
      </div>
    </header>
  );
}
```

- [ ] **Step 3: AppShell（定义 ViewMode 并编排布局与现有视图/Modal）**

Create `web/src/layout/AppShell.tsx`. 复制现有 `App.tsx`（`web/src/App.tsx`）中的 query、Modal 状态与视图渲染逻辑，改为侧边栏驱动。完整内容：

```tsx
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Layout, Spin } from 'antd';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import type { Application } from '@/types/application';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import KanbanBoard from '@/components/KanbanBoard';
import AddApplicationForm from '@/components/AddApplicationForm';
import ApplicationDetail from '@/components/ApplicationDetail';
import ResumeMatchModal from '@/components/ResumeMatchModal';
import CalendarView from '@/components/CalendarView';
import ChatPanel from '@/components/ChatPanel';
import ReviewManagementView from '@/components/ReviewManagementView';
import KnowledgeBaseView from '@/components/KnowledgeBaseView';
import OfferCenterView from '@/components/OfferCenterView';
import DashboardView from '@/features/dashboard/DashboardView';
import RemindersView from '@/features/reminders/RemindersView';
import { deriveReminders, reminderBadgeCount } from '@/lib/insights';
import dayjs from 'dayjs';

const { Content } = Layout;

export type ViewMode =
  | 'dashboard'
  | 'board'
  | 'calendar'
  | 'reminders'
  | 'reviews'
  | 'offers'
  | 'knowledge';

function computeStreak(apps: Application[], now = dayjs()): number {
  const days = new Set(
    apps.filter((a) => a.applied_at).map((a) => dayjs(a.applied_at).format('YYYY-MM-DD'))
  );
  let streak = 0;
  let cursor = now;
  while (days.has(cursor.format('YYYY-MM-DD'))) {
    streak++;
    cursor = cursor.subtract(1, 'day');
  }
  return streak;
}

export default function AppShell() {
  const [view, setView] = useState<ViewMode>('dashboard');
  const [addOpen, setAddOpen] = useState(false);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [selected, setSelected] = useState<Application | null>(null);
  const [coachOfferId, setCoachOfferId] = useState<number | undefined>(undefined);

  const { data: applications = [], isLoading } = useQuery({
    queryKey: ['applications'],
    queryFn: () => listApplications(),
  });
  const { data: events = [] } = useQuery({
    queryKey: ['events'],
    queryFn: () => listEvents(),
  });

  const reminders = useMemo(
    () => deriveReminders(applications, events, [], dayjs()),
    [applications, events]
  );
  const streak = useMemo(() => computeStreak(applications), [applications]);

  const selectedApp = selected
    ? applications.find((a) => a.id === selected.id) ?? selected
    : null;

  const openChat = (offerId?: number) => {
    setCoachOfferId(offerId);
    setChatOpen(true);
  };

  const goDetailById = (appId: number) => {
    const app = applications.find((a) => a.id === appId);
    if (app) setSelected(app);
  };

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--op-layout-bg)' }} hasSider>
      <Sidebar
        view={view}
        onChange={setView}
        reminderCount={reminderBadgeCount(reminders)}
        onOpenChat={() => openChat(undefined)}
      />
      <Layout style={{ background: 'var(--op-layout-bg)' }}>
        <TopBar streakDays={streak} onAdd={() => setAddOpen(true)} onSearch={() => setResumeOpen(true)} />
        <Content style={{ padding: '0 24px 24px' }}>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : (
            <div className="op-view-enter" key={view}>
              {view === 'dashboard' && (
                <DashboardView onNavigate={setView} onOpenDetailById={goDetailById} />
              )}
              {view === 'board' && (
                <KanbanBoard applications={applications} onOpenDetail={(a) => setSelected(a)} />
              )}
              {view === 'calendar' && (
                <CalendarView applications={applications} onOpenDetail={(a) => setSelected(a)} />
              )}
              {view === 'reminders' && (
                <RemindersView onNavigate={setView} onOpenDetailById={goDetailById} />
              )}
              {view === 'reviews' && <ReviewManagementView applications={applications} />}
              {view === 'offers' && (
                <OfferCenterView applications={applications} onCoach={(offer) => openChat(offer.id)} />
              )}
              {view === 'knowledge' && <KnowledgeBaseView />}
            </div>
          )}
        </Content>
      </Layout>

      <AddApplicationForm open={addOpen} onClose={() => setAddOpen(false)} />
      <ApplicationDetail application={selectedApp} open={!!selected} onClose={() => setSelected(null)} />
      <ResumeMatchModal open={resumeOpen} onClose={() => setResumeOpen(false)} />
      <ChatPanel
        open={chatOpen}
        onClose={() => {
          setChatOpen(false);
          setCoachOfferId(undefined);
        }}
        offerId={coachOfferId}
      />
    </Layout>
  );
}
```

> 注：此步引用了尚未创建的 `DashboardView`（Task 7）与 `RemindersView`（Task 6）。因此本任务的类型检查放在 Task 6/7 之后统一进行——见 Step 4。为让 Task 4 可独立提交，先创建两个最小占位组件。

- [ ] **Step 4: 创建两个最小占位组件（后续任务替换）**

Create `web/src/features/dashboard/DashboardView.tsx`:

```tsx
import type { ViewMode } from '@/layout/AppShell';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

export default function DashboardView(_props: Props) {
  return <div style={{ padding: 24, color: 'var(--op-muted)' }}>驾驶舱（待实现）</div>;
}
```

Create `web/src/features/reminders/RemindersView.tsx`:

```tsx
import type { ViewMode } from '@/layout/AppShell';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

export default function RemindersView(_props: Props) {
  return <div style={{ padding: 24, color: 'var(--op-muted)' }}>提醒中心（待实现）</div>;
}
```

- [ ] **Step 5: 类型检查**

Run: `cd web && npx tsc -b`
Expected: PASS。若 `_props`/`onNavigate` 未使用报错，占位组件参数前缀 `_` 或加 `// eslint-disable`；tsc 的 `noUnusedParameters` 若开启则参数用 `_` 前缀即可（已用 `_props`）。

- [ ] **Step 6: 提交**

```bash
git add web/src/layout web/src/features/dashboard/DashboardView.tsx web/src/features/reminders/RemindersView.tsx
git commit -m "feat(layout): app shell with persistent sidebar and topbar"
```

---

## Task 5: 用 AppShell 替换旧 App.tsx

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: 替换 App.tsx**

Replace the full content of `web/src/App.tsx` with:

```tsx
import AppShell from './layout/AppShell';

export default function App() {
  return <AppShell />;
}
```

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd web && npx tsc -b && npm run build`
Expected: PASS，产物生成到 `web/dist`。

- [ ] **Step 3: 手动走查**

Run: `cd web && npm run dev`，浏览器打开 dev 地址。确认：侧边栏 7 项可切换、旧 5 视图正常渲染、明暗切换生效、顶栏按钮打开对应 Modal、驾驶舱/提醒显示占位文案。

- [ ] **Step 4: 提交**

```bash
git add web/src/App.tsx
git commit -m "refactor(app): render AppShell, remove legacy header/segmented/statistics"
```

---

## Task 6: 提醒中心页面

**Files:**
- Create: `web/src/features/reminders/reminders.module.css`
- Modify (replace placeholder): `web/src/features/reminders/RemindersView.tsx`

- [ ] **Step 1: 样式**

Create `web/src/features/reminders/reminders.module.css`:

```css
.wrap { display: flex; flex-direction: column; gap: 20px; }
.group { display: flex; flex-direction: column; gap: 10px; }
.groupTitle {
  font-size: 13px;
  font-weight: 600;
  color: var(--op-muted);
  letter-spacing: 0.02em;
}
.item {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--op-surface);
  border-radius: 14px;
  padding: 14px 16px;
  box-shadow: var(--op-shadow-md);
  cursor: pointer;
  transition: transform 0.18s var(--op-ease), box-shadow 0.18s var(--op-ease);
  animation: itemIn 0.25s var(--op-ease) backwards;
}
.item:hover { transform: translateY(-1px); box-shadow: var(--op-shadow-lg); }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.red { background: var(--op-error); }
.amber { background: var(--op-warning); }
.green { background: var(--op-success); }
.body { flex: 1; min-width: 0; }
.title { font-size: 14px; color: var(--op-ink); font-weight: 500; }
.detail { font-size: 12px; color: var(--op-muted); margin-top: 2px; }
.empty {
  text-align: center;
  padding: 64px 0;
  color: var(--op-muted);
  font-size: 14px;
}
@keyframes itemIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .item { animation: none; }
}
```

- [ ] **Step 2: 组件**

Replace the full content of `web/src/features/reminders/RemindersView.tsx` with:

```tsx
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import { deriveReminders, type Reminder, type ReminderSeverity } from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import styles from './reminders.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

const GROUPS: { key: ReminderSeverity; label: string }[] = [
  { key: 'red', label: '今日紧急' },
  { key: 'amber', label: '本周关注' },
  { key: 'green', label: '进行中' },
];

export default function RemindersView({ onNavigate, onOpenDetailById }: Props) {
  const { data: apps = [] } = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const { data: events = [] } = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const { data: offers = [] } = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });

  const reminders = useMemo(
    () => deriveReminders(apps, events, offers, dayjs()),
    [apps, events, offers]
  );

  const handleClick = (r: Reminder) => {
    if (r.target === 'board' && r.appId) {
      onOpenDetailById(r.appId);
    } else {
      onNavigate(r.target);
    }
  };

  if (reminders.length === 0) {
    return <div className={styles.empty}>暂无待办，保持节奏 ✦</div>;
  }

  return (
    <div className={styles.wrap}>
      {GROUPS.map(({ key, label }) => {
        const items = reminders.filter((r) => r.severity === key);
        if (items.length === 0) return null;
        return (
          <div key={key} className={styles.group}>
            <div className={styles.groupTitle}>
              {label}（{items.length}）
            </div>
            {items.map((r, i) => (
              <div
                key={r.id}
                className={styles.item}
                style={{ animationDelay: `${i * 40}ms` }}
                onClick={() => handleClick(r)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && handleClick(r)}
              >
                <span className={`${styles.dot} ${styles[r.severity]}`} />
                <div className={styles.body}>
                  <div className={styles.title}>{r.title}</div>
                  <div className={styles.detail}>{r.detail}</div>
                </div>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: 确认 listOffers 存在**

Run: `grep -n "listOffers\|export async function" web/src/services/offers.ts`
Expected: 找到 `listOffers`。若列表函数名不同，替换 import 与调用处。

- [ ] **Step 4: 类型检查**

Run: `cd web && npx tsc -b`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add web/src/features/reminders
git commit -m "feat(reminders): reminder center with stale/interview/offer rules"
```

---

## Task 7: 驾驶舱主页 + widgets

**Files:**
- Create: `web/src/features/dashboard/dashboard.module.css`
- Create: `web/src/features/dashboard/widgets/KpiCards.tsx`
- Create: `web/src/features/dashboard/widgets/ConversionFunnel.tsx`
- Create: `web/src/features/dashboard/widgets/MomentumChart.tsx`
- Create: `web/src/features/dashboard/widgets/UpcomingSchedule.tsx`
- Create: `web/src/features/dashboard/widgets/RemindersSummary.tsx`
- Modify (replace placeholder): `web/src/features/dashboard/DashboardView.tsx`

- [ ] **Step 1: 样式**

Create `web/src/features/dashboard/dashboard.module.css`:

```css
.grid { display: flex; flex-direction: column; gap: 14px; }
.kpiRow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.row2 { display: grid; grid-template-columns: 1.3fr 1fr; gap: 12px; }
.row2b { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.card {
  background: var(--op-surface);
  border-radius: 14px;
  padding: 15px;
  box-shadow: var(--op-shadow-md);
}
.cardTitle { font-size: 13px; font-weight: 600; color: var(--op-ink); margin-bottom: 12px; }
.kpiLabel { font-size: 11px; color: var(--op-muted); }
.kpiValue { font-size: 26px; font-weight: 700; color: var(--op-ink); }
.kpiHint { font-size: 10px; margin-top: 2px; }
.up { color: var(--op-success); }
.muted { color: var(--op-muted); }

.funnelRow { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.funnelLabel { font-size: 11px; color: var(--op-muted); width: 44px; flex-shrink: 0; }
.funnelBarWrap { flex: 1; height: 20px; background: var(--op-layout-bg); border-radius: 6px; overflow: hidden; }
.funnelBar { height: 100%; border-radius: 6px; transition: width 0.4s var(--op-ease); }
.funnelCount { font-size: 12px; width: 28px; text-align: right; flex-shrink: 0; }

.bars { display: flex; gap: 6px; align-items: flex-end; height: 60px; }
.bar { flex: 1; border-radius: 5px 5px 0 0; background: var(--op-gradient-brand); min-height: 4px; transition: height 0.4s var(--op-ease); }
.barLabel { font-size: 9px; color: var(--op-muted); text-align: center; margin-top: 4px; }

.schedItem { display: flex; gap: 10px; margin-bottom: 10px; }
.schedDate { text-align: center; flex-shrink: 0; }
.schedMon { font-size: 9px; color: var(--op-muted); }
.schedDay { font-size: 16px; font-weight: 700; color: var(--op-primary); }
.schedText { font-size: 12px; color: var(--op-ink); padding-top: 4px; }
.empty { color: var(--op-muted); font-size: 12px; }

@media (max-width: 900px) {
  .kpiRow { grid-template-columns: repeat(2, 1fr); }
  .row2, .row2b { grid-template-columns: 1fr; }
}
```

- [ ] **Step 2: KpiCards**

Create `web/src/features/dashboard/widgets/KpiCards.tsx`:

```tsx
import type { Kpis } from '@/lib/insights';
import styles from '../dashboard.module.css';

export default function KpiCards({ kpis }: { kpis: Kpis }) {
  const cards = [
    { label: '总投递', value: kpis.total, hint: kpis.weeklyDelta > 0 ? `↑ 本周 +${kpis.weeklyDelta}` : '本周无新增', up: kpis.weeklyDelta > 0 },
    { label: '面试中', value: kpis.interviewing, hint: '进行中', up: false },
    { label: 'Offer', value: kpis.offers, hint: kpis.offers > 0 ? '已到手' : '继续冲', up: kpis.offers > 0 },
    { label: '响应率', value: `${Math.round(kpis.responseRate * 100)}%`, hint: '收到回音占比', up: false },
  ];
  return (
    <div className={styles.kpiRow}>
      {cards.map((c) => (
        <div key={c.label} className={styles.card}>
          <div className={styles.kpiLabel}>{c.label}</div>
          <div className={`${styles.kpiValue} op-tnum`}>{c.value}</div>
          <div className={`${styles.kpiHint} ${c.up ? styles.up : styles.muted}`}>{c.hint}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: ConversionFunnel**

Create `web/src/features/dashboard/widgets/ConversionFunnel.tsx`:

```tsx
import type { FunnelStage } from '@/lib/insights';
import styles from '../dashboard.module.css';

const COLORS = ['#6366f1', '#7c6ff2', '#a855f7', '#059669'];

export default function ConversionFunnel({ stages }: { stages: FunnelStage[] }) {
  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>转化漏斗</div>
      {stages.map((s, i) => (
        <div key={s.key} className={styles.funnelRow}>
          <span className={styles.funnelLabel}>{s.label}</span>
          <div className={styles.funnelBarWrap}>
            <div
              className={styles.funnelBar}
              style={{ width: `${Math.max(s.ratio * 100, 3)}%`, background: COLORS[i] }}
            />
          </div>
          <span className={`${styles.funnelCount} op-tnum`} style={{ color: COLORS[i] }}>
            {s.count}
          </span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: MomentumChart**

Create `web/src/features/dashboard/widgets/MomentumChart.tsx`:

```tsx
import type { MomentumBucket } from '@/lib/insights';
import styles from '../dashboard.module.css';

export default function MomentumChart({ buckets }: { buckets: MomentumBucket[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>近 4 周动量</div>
      <div className={styles.bars}>
        {buckets.map((b) => (
          <div key={b.label} style={{ flex: 1 }}>
            <div className={styles.bar} style={{ height: `${(b.count / max) * 100}%` }} title={`${b.count} 个`} />
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {buckets.map((b) => (
          <div key={b.label} className={styles.barLabel} style={{ flex: 1 }}>
            {b.label}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: UpcomingSchedule**

Create `web/src/features/dashboard/widgets/UpcomingSchedule.tsx`:

```tsx
import dayjs from 'dayjs';
import type { ScheduleEvent } from '@/types/event';
import { EVENT_TYPE_LABELS } from '@/types/event';
import styles from '../dashboard.module.css';

export default function UpcomingSchedule({ events }: { events: ScheduleEvent[] }) {
  const upcoming = events
    .filter((e) => e.scheduled_at && dayjs(e.scheduled_at).isAfter(dayjs()))
    .sort((a, b) => dayjs(a.scheduled_at).valueOf() - dayjs(b.scheduled_at).valueOf())
    .slice(0, 5);

  return (
    <div className={styles.card}>
      <div className={styles.cardTitle}>近期日程</div>
      {upcoming.length === 0 ? (
        <div className={styles.empty}>暂无安排</div>
      ) : (
        upcoming.map((e) => {
          const d = dayjs(e.scheduled_at);
          return (
            <div key={e.id} className={styles.schedItem}>
              <div className={styles.schedDate}>
                <div className={styles.schedMon}>{d.format('M月')}</div>
                <div className={`${styles.schedDay} op-tnum`}>{d.format('DD')}</div>
              </div>
              <div className={styles.schedText}>
                {e.company_name ?? '安排'} {EVENT_TYPE_LABELS[e.event_type]} · {d.format('HH:mm')}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
```

- [ ] **Step 6: RemindersSummary**

Create `web/src/features/dashboard/widgets/RemindersSummary.tsx`:

```tsx
import type { Reminder } from '@/lib/insights';
import styles from '../dashboard.module.css';

const DOT: Record<string, string> = {
  red: 'var(--op-error)',
  amber: 'var(--op-warning)',
  green: 'var(--op-success)',
};

interface Props {
  reminders: Reminder[];
  onSeeAll: () => void;
}

export default function RemindersSummary({ reminders, onSeeAll }: Props) {
  const top = reminders.slice(0, 4);
  return (
    <div className={styles.card}>
      <div
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}
      >
        <span className={styles.cardTitle} style={{ margin: 0 }}>待跟进</span>
        <a onClick={onSeeAll} style={{ fontSize: 12, cursor: 'pointer', color: 'var(--op-primary)' }}>
          全部 →
        </a>
      </div>
      {top.length === 0 ? (
        <div className={styles.empty}>暂无待办 ✦</div>
      ) : (
        top.map((r) => (
          <div key={r.id} style={{ display: 'flex', gap: 9, alignItems: 'center', marginBottom: 9 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: DOT[r.severity], flexShrink: 0 }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12, color: 'var(--op-ink)' }}>{r.title}</div>
              <div style={{ fontSize: 10, color: 'var(--op-muted)' }}>{r.detail}</div>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 7: DashboardView 组装**

Replace the full content of `web/src/features/dashboard/DashboardView.tsx` with:

```tsx
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Skeleton } from 'antd';
import dayjs from 'dayjs';
import { listApplications } from '@/services/applications';
import { listEvents } from '@/services/events';
import { listOffers } from '@/services/offers';
import {
  computeKpis,
  computeFunnel,
  computeMomentum,
  deriveReminders,
} from '@/lib/insights';
import type { ViewMode } from '@/layout/AppShell';
import KpiCards from './widgets/KpiCards';
import ConversionFunnel from './widgets/ConversionFunnel';
import MomentumChart from './widgets/MomentumChart';
import UpcomingSchedule from './widgets/UpcomingSchedule';
import RemindersSummary from './widgets/RemindersSummary';
import styles from './dashboard.module.css';

interface Props {
  onNavigate: (v: ViewMode) => void;
  onOpenDetailById: (id: number) => void;
}

export default function DashboardView({ onNavigate }: Props) {
  const appsQ = useQuery({ queryKey: ['applications'], queryFn: () => listApplications() });
  const eventsQ = useQuery({ queryKey: ['events'], queryFn: () => listEvents() });
  const offersQ = useQuery({ queryKey: ['offers'], queryFn: () => listOffers() });

  const apps = appsQ.data ?? [];
  const events = eventsQ.data ?? [];
  const offers = offersQ.data ?? [];

  const kpis = useMemo(() => computeKpis(apps), [apps]);
  const funnel = useMemo(() => computeFunnel(apps), [apps]);
  const momentum = useMemo(() => computeMomentum(apps), [apps]);
  const reminders = useMemo(() => deriveReminders(apps, events, offers, dayjs()), [apps, events, offers]);

  if (appsQ.isLoading) {
    return <Skeleton active paragraph={{ rows: 8 }} />;
  }

  return (
    <div className={styles.grid}>
      <KpiCards kpis={kpis} />
      <div className={styles.row2}>
        <ConversionFunnel stages={funnel} />
        <RemindersSummary reminders={reminders} onSeeAll={() => onNavigate('reminders')} />
      </div>
      <div className={styles.row2b}>
        <MomentumChart buckets={momentum} />
        <UpcomingSchedule events={events} />
      </div>
    </div>
  );
}
```

- [ ] **Step 8: 类型检查 + 构建**

Run: `cd web && npx tsc -b && npm run build`
Expected: PASS。若 `UpcomingSchedule` 中 `dayjs(...).isAfter` 报类型错，确认 dayjs 版本（现为 1.11），`isAfter` 为内置方法，无需插件。

- [ ] **Step 9: 手动走查**

Run: `cd web && npm run dev`。确认驾驶舱显示 KPI/漏斗/待跟进/动量/日程；造几条不同状态/日期的投递与 event 验证漏斗与提醒摘要联动；点"全部 →"跳到提醒页。

- [ ] **Step 10: 提交**

```bash
git add web/src/features/dashboard
git commit -m "feat(dashboard): cockpit home with kpis, funnel, momentum, schedule, reminders"
```

---

## Task 8: 命令面板（⌘K）+ 简历匹配/AI 归并

**Files:**
- Create: `web/src/layout/CommandPalette.tsx`
- Modify: `web/src/layout/AppShell.tsx`
- Modify: `web/src/layout/TopBar.tsx`

- [ ] **Step 1: CommandPalette 组件**

Create `web/src/layout/CommandPalette.tsx`:

```tsx
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
```

- [ ] **Step 2: 在 AppShell 接入命令面板 + ⌘K 快捷键**

在 `web/src/layout/AppShell.tsx` 中做以下修改：

1. 顶部 import 追加：
```tsx
import { useEffect } from 'react';
import CommandPalette from './CommandPalette';
```
（若已 import `useMemo, useState`，把 `useEffect` 合并进现有 `react` import 行。）

2. 在其它 `useState` 附近新增：
```tsx
const [paletteOpen, setPaletteOpen] = useState(false);
```

3. 新增快捷键监听（放在 query hooks 之后）：
```tsx
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      setPaletteOpen((v) => !v);
    }
  };
  window.addEventListener('keydown', onKey);
  return () => window.removeEventListener('keydown', onKey);
}, []);
```

4. 把 `TopBar` 的 `onSearch` 改为打开命令面板：
```tsx
<TopBar streakDays={streak} onAdd={() => setAddOpen(true)} onSearch={() => setPaletteOpen(true)} />
```

5. 在 `<ResumeMatchModal ... />` 之后新增：
```tsx
<CommandPalette
  open={paletteOpen}
  onClose={() => setPaletteOpen(false)}
  applications={applications}
  onNavigate={setView}
  onOpenDetail={(app) => setSelected(app)}
  onAddApplication={() => setAddOpen(true)}
  onOpenResume={() => setResumeOpen(true)}
  onOpenChat={() => openChat(undefined)}
/>
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd web && npx tsc -b && npm run build`
Expected: PASS

- [ ] **Step 4: 手动走查**

Run: `cd web && npm run dev`。按 `⌘K`/`Ctrl+K` 或点顶栏搜索：输入公司名匹配投递并打开详情；输入"简历"命中简历匹配动作；导航命令切换视图。

- [ ] **Step 5: 提交**

```bash
git add web/src/layout/CommandPalette.tsx web/src/layout/AppShell.tsx web/src/layout/TopBar.tsx
git commit -m "feat(command-palette): global cmd+k search, nav, and actions"
```

---

## Task 9: 看板视觉对齐 + 空/错误态 + 响应式收尾

**Files:**
- Modify: `web/src/components/KanbanBoard/KanbanBoard.module.css`
- Modify: `web/src/layout/AppShell.tsx`（错误态）

- [ ] **Step 1: 看板配色对齐柔和调板**

编辑 `web/src/components/KanbanBoard/KanbanBoard.module.css`，将硬编码的中性色/阴影替换为 token（保留结构与尺寸）：

- `.column` 的 `background: #f8fafc` → `background: var(--op-layout-bg)`；`border: 1px solid #e2e8f0` → `border: 1px solid var(--op-border)`。
- `.columnHeader` 的 `background: #ffffff` → `background: var(--op-surface)`；`color: #0f172a` → `color: var(--op-ink)`；`border-bottom` 颜色 → `var(--op-border)`。
- `.card` 的 `background: #ffffff` → `var(--op-surface)`；`box-shadow: 0 8px 18px rgba(15,23,42,0.06)` → `box-shadow: var(--op-shadow-md)`；`border` 颜色 → `var(--op-border)`。
- `.card:hover` 的 `box-shadow` → `var(--op-shadow-lg)`。
- `.cardName` 颜色 `#0f172a` → `var(--op-ink)`；`.cardCompany`/`.cardDate`/`.cardNotes` 的灰色 → `var(--op-muted)`。
- `.emptyColumn` 的 `background: #ffffff` → `var(--op-surface)`；边框/文字色 → `var(--op-border)`/`var(--op-muted)`。

保存后颜色随明暗模式自动适配（因引用 CSS 变量）。

- [ ] **Step 2: 数据错误态**

在 `web/src/layout/AppShell.tsx` 的 `Content` 渲染分支中，加载态之外补一个错误态。将现有：
```tsx
{isLoading ? (
  <div style={{ textAlign: 'center', padding: 48 }}>
    <Spin size="large" />
  </div>
) : (
```
改为：
```tsx
{isLoading ? (
  <div style={{ textAlign: 'center', padding: 48 }}>
    <Spin size="large" />
  </div>
) : appsError ? (
  <div style={{ textAlign: 'center', padding: 48, color: 'var(--op-muted)' }}>
    加载失败，请稍后重试
  </div>
) : (
```
并在 `useQuery` 解构处取出错误：
```tsx
const { data: applications = [], isLoading, isError: appsError } = useQuery({
  queryKey: ['applications'],
  queryFn: () => listApplications(),
});
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd web && npx tsc -b && npm run build`
Expected: PASS

- [ ] **Step 4: 手动走查（明暗 + 响应式）**

Run: `cd web && npm run dev`。切暗色确认看板/驾驶舱/提醒配色协调；缩窄窗口到 <900px 确认驾驶舱网格回落单列、看板可横向滚动。

- [ ] **Step 5: 提交**

```bash
git add web/src/components/KanbanBoard/KanbanBoard.module.css web/src/layout/AppShell.tsx
git commit -m "style(kanban): align to soft-premium tokens; add error state"
```

---

## Task 10: 全量构建 + 收尾走查

- [ ] **Step 1: 全量构建**

Run: `cd web && npm run build`
Expected: PASS，无类型错误，`web/dist` 产物生成。

- [ ] **Step 2: 端到端走查清单**

Run: `cd web && npm run dev`，逐项确认：
- 侧边栏 7 项切换 + 选中态 + 提醒红点计数正确。
- 驾驶舱：4 KPI、漏斗、待跟进、动量、日程均渲染，数据合理。
- 提醒中心：三类规则分组显示，点击跳转正确。
- ⌘K：搜索/导航/动作可用。
- 明暗模式切换持久（刷新后保持）。
- 现有看板/日历/复盘/谈薪/知识库/AI 助手/添加投递/简历匹配功能未回归。
- 窄屏响应式正常。

- [ ] **Step 3: 最终提交（若走查有微调）**

```bash
git add -A
git commit -m "chore(ui): final polish and walkthrough fixes"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计系统(Task1-2)、IA/外壳(Task4-5)、提醒中心(Task6)、驾驶舱(Task7)、命令面板+简历归并(Task8)、视觉对齐+状态(Task9)、验证(Task5/7/8/9/10)。字体自托管改为系统栈（已在计划顶部说明偏差）。均有对应任务。
- **占位符**：Task4 Step3 引用后续任务组件，已用最小占位组件消解，保证每任务可独立编译提交。
- **类型一致**：`ViewMode` 在 AppShell 定义并被 Sidebar/Dashboard/Reminders/CommandPalette 统一 import；`Reminder`/`Kpis`/`FunnelStage`/`MomentumBucket` 均来自 `insights.ts`；`listOffers` 在 Task3 Step1 与 Task6 Step3 校验实际名称。
- **风险点**：`listOffers` 实际导出名需在 Task3/6 校验；dayjs 比较方法为内置；`tsconfig` 若开 `noUnusedParameters`，占位组件已用 `_` 前缀参数。
