# OfferPilot 前端重构设计：高级柔和视觉系统 + 求职驾驶舱 + 提醒中心

- 日期：2026-07-01
- 分支：`feat/ui-redesign`（worktree：`.worktrees/feat-ui-redesign`）
- 范围：视觉 + 功能双线扩展（保留全部现有功能逻辑）

---

## 1. 背景与目标

OfferPilot 功能骨架已完整（看板 / 日历 / 复盘 / 谈薪 / 知识库 / AI 助手 / 简历匹配），但界面是近乎默认的 Ant Design：无主题 token、无品牌识别、平铺式 `Segmented` 导航、裸 `Statistic` 概览、缺状态设计与动效。

本次目标：

1. **建立统一设计语言**——「高级柔和」（Linear / Apple 级质感）：柔和渐变、精致圆角、轻盈彩色阴影、流畅动效，含完整设计 token + 暗色模式。
2. **重构信息架构**——用持久侧边栏取代 `Segmented`，新增「驾驶舱」主页与「提醒」页面。
3. **新增两个功能**：
   - **求职驾驶舱（Dashboard 主页）**——一屏总览 KPI、转化漏斗、待跟进、动量、近期日程。
   - **提醒中心**——投递停滞、面试倒计时、Offer 答复期三类规则驱动的跟进提醒。

**非目标（YAGNI）**：不改后端 / 不加新接口（所有指标客户端派生）、不做 mock 面试等新 AI 能力、不引入前端路由库、不做英文 i18n、不新建独立"深度分析"页（仅驾驶舱摘要 + 漏斗）。

---

## 2. 技术约束

- 现有栈：React 18 + TypeScript + Vite + Ant Design 5 + TanStack Query + axios + dayjs。沿用，不新增重依赖。
- **离线优先**：OfferPilot 100% 本地部署，禁止运行时依赖外部 CDN 字体/资源。自托管字体需打进构建产物。
- 现有导航是 `App.tsx` 里的 `viewMode` 状态切换（无 router）。**沿用状态式路由**，侧边栏与命令面板均通过设置 `viewMode` / 打开 modal 实现，避免引入 react-router 的迁移成本。

---

## 3. 设计系统（Design Tokens）

### 3.1 色彩

| 角色 | 值 | 说明 |
|---|---|---|
| Primary（靛蓝） | `#6366f1` | 主色，按钮 / 选中态 / 链接 |
| Accent（紫） | `#a855f7` | 与主色组成品牌渐变 `linear-gradient(135deg,#6366f1,#a855f7)` |
| Success（翠绿） | `#059669` | Offer / 正向趋势 |
| Warning（琥珀） | `#d97706` | 面试中 / 临近提醒 |
| Error（红） | `#ef4444` | 逾期 / 被拒 / 徽标计数 |
| Ink（墨） | `#23213a` | 主文字（带极轻靛色调） |
| Muted | `#8b87b3` | 次要文字 |
| Layout BG | `#f6f6fb` | 页面底色（柔和薰衣草灰） |
| Surface | `#ffffff` | 卡片 |

状态色沿用现有 `STATUS_COLORS` / `OFFER_STATUS_COLORS` 语义，但在需要时向柔和调板对齐。

### 3.2 排版

- **CJK 正文**：系统栈 `"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif`（离线安全、中文表现好）。
- **拉丁/展示/数字**：自托管一款变量字体（`Plus Jakarta Sans`，woff2 打进构建）用于品牌名、标题、数字。
- 数字统一 `font-variant-numeric: tabular-nums`（KPI、表格、金额对齐 —— 来自 make-interfaces-feel-better）。
- 文本抗锯齿 `-webkit-font-smoothing: antialiased`。

### 3.3 圆角 / 阴影 / 间距

- 圆角：token `borderRadius: 12`；卡片 14px；按钮 10px；徽标/胶囊 999px（仅小元素）。
- 阴影：柔和彩色低透明度，禁用 AntD 默认深灰硬阴影。定义 CSS 变量：
  - `--shadow-sm: 0 1px 4px rgba(31,29,58,.05)`
  - `--shadow-md: 0 2px 10px rgba(99,102,241,.08)`
  - `--shadow-lg: 0 8px 28px rgba(99,102,241,.14)`
- 间距用 4 的倍数（4/8/12/16/20/24），保证宏观留白。

### 3.4 动效（make-interfaces-feel-better + soft-skill）

- 缓动统一 `cubic-bezier(.22,1,.36,1)`，禁用 `linear`。
- 视图切换：`opacity + translateY(6px)` 淡入（~220ms）。
- 卡片 hover：上移 1–2px + 阴影加深。
- KPI 数字入场 count-up（可选、克制）。
- 命令面板 / 抽屉：scale + fade。
- 提醒条目 stagger 入场。
- 全局尊重 `prefers-reduced-motion: reduce`（关闭位移/count-up）。

### 3.5 暗色模式

- AntD `theme.darkAlgorithm` + 暗色 token 覆盖（BG `#141322`，Surface `#1c1a2e`，Ink `#e7e5f2`）。
- 暗色下阴影改为发光/描边，渐变降饱和。
- 切换开关放侧边栏底部，状态持久化到 `localStorage`（key `op-theme`），默认跟随系统。

### 3.6 落地方式

- `web/src/theme/antdTheme.ts`——导出 `lightTheme` / `darkTheme`（ConfigProvider `theme` 对象：token + components 覆盖）。
- `web/src/theme/tokens.css`——CSS 自定义属性（渐变、阴影、缓动、间距）。
- `web/src/theme/fonts.css`——`@font-face` 自托管字体。
- `main.tsx` 用 `ConfigProvider theme={...}` 注入，并加主题上下文（明/暗切换）。

---

## 4. 信息架构 / 应用外壳

```
┌────────────┬──────────────────────────────────────────┐
│  Sidebar   │  TopBar: 问候+连续天数 | ⌘K搜索 | +添加投递  │
│            ├──────────────────────────────────────────┤
│  驾驶舱     │                                          │
│  看板       │           Content（当前视图）              │
│  日历       │                                          │
│  提醒 ●3    │                                          │
│  复盘       │                                          │
│  谈薪       │                                          │
│  知识库     │                                          │
│  ────────  │                                          │
│  ✦AI助手    │                                          │
│  ☾ 暗色     │                                          │
└────────────┴──────────────────────────────────────────┘
```

- **Sidebar**：品牌区 + 7 个导航项（驾驶舱 / 看板 / 日历 / 提醒 / 复盘 / 谈薪 / 知识库）。「提醒」带红色计数徽标（= 紧急+临近提醒数）。底部：AI 助手唤起入口、暗色切换。
  - 响应式：`<1024px` 收成图标窄轨；`<768px` 变抽屉，顶部加汉堡按钮。
- **TopBar**：左侧问候语 + 日期 + 连续投递天数；右侧 `⌘K` 搜索入口 + 主按钮「添加投递」。
- **CommandPalette（⌘K）**：全局搜索投递/公司/Offer，跳转视图，触发动作（添加投递、简历匹配、AI 助手）。**简历匹配** 不再占导航，收进此处与 AI 助手内。
- **AI 助手**：保留现有 `ChatPanel` 抽屉式实现，由侧边栏底部/命令面板唤起。

`viewMode` 类型扩展为：`'dashboard' | 'board' | 'calendar' | 'reminders' | 'reviews' | 'offers' | 'knowledge'`，默认 `'dashboard'`。

---

## 5. 求职驾驶舱（Dashboard 主页）

新组件 `web/src/features/dashboard/DashboardView.tsx`，由若干 widget 组成，数据来自 `listApplications` / `listEvents` / `listOffers`（TanStack Query）。所有计算放纯函数模块 `web/src/lib/insights.ts`。

| Widget | 内容 | 数据来源 |
|---|---|---|
| **KPI 卡 ×4** | 总投递、面试中、Offer、响应率（含 ↑/↓ 周环比趋势） | applications |
| **转化漏斗** | 投递 → 初筛/测评 → 面试 → Offer 各级数量与占比 | applications 按 status 聚合 |
| **待跟进摘要** | 取提醒中心前 3–4 条最紧急项 | insights.deriveReminders |
| **近 N 周动量** | 每周新增投递柱状（纯 CSS/SVG，不引图表库） | applications.applied_at |
| **近期日程** | 未来最近 3–5 个面试/笔试 | events |

- **响应率** = (进入过初筛及以后状态的投递数) / 总投递数。
- 空状态：无数据时展示引导卡（"添加第一个投递"CTA）。
- 加载态：各 widget 骨架屏。

---

## 6. 提醒中心

新组件 `web/src/features/reminders/RemindersView.tsx` + 派生逻辑 `insights.deriveReminders(apps, events, offers, now)`（纯函数，返回排序后的 `Reminder[]`）。

### 6.1 提醒规则

| 类型 | 触发条件 | 文案示例 | 严重度 |
|---|---|---|---|
| **投递停滞** | status ∈ {applied, assessment, written_test} 且距 `updated_at` > 阈值（默认 7 天） | "字节·后端 已投 7 天无回音，建议跟进" | 停 8–14 天=amber，>14 天=red |
| **面试倒计时** | event.scheduled_at 在未来 72h 内 | "阿里·二面 明天 14:00，去准备" | <24h=red，≤72h=amber |
| **Offer 答复期** | offer.status ∈ {pending, negotiating} 且 deadline 在未来 7 天内 | "美团 Offer 还剩 3 天答复期" | ≤2 天=red，≤7 天=amber |
| **缺下一步（可选）** | status=interview 但无未来 event | "面试进行中，未安排下一场" | amber |

- **徽标计数** = red + amber 提醒总数。
- 排序：red → amber → green，同级按时间紧迫度。
- 阈值集中在 `insights.ts` 常量，便于后续做成设置。

### 6.2 UI

- 分组列表（今日紧急 / 本周关注 / 已安排），每条含状态圆点、公司·职位、说明、快捷操作（跳转到对应投递详情 / 日历 / Offer）。
- 空状态："暂无待办，保持节奏 ✦"。

---

## 7. 现有视图迁移

现有组件在新外壳内复用，主要做**视觉对齐**而非重写：

- **KanbanBoard**：更新 `KanbanBoard.module.css` 到柔和调板（列头彩色语义、卡片阴影用 `--shadow-md`、hover 上移），沿用 dnd-kit 逻辑。
- **CalendarView / ReviewManagementView / OfferCenterView / KnowledgeBaseView**：主要由 AntD 主题 token 自动继承新样式；对自定义 CSS/内联样式做柔和化微调（圆角、阴影、语义色）。
- **各 Modal / Drawer / Form**：主题 token 自动生效；统一圆角与主按钮渐变。
- 原 `App.tsx` 顶部 `Statistic` 行删除（能力并入驾驶舱）。

---

## 8. 组件与文件结构

```
web/src/
  theme/
    antdTheme.ts        # light/dark ConfigProvider theme
    tokens.css          # CSS 变量（渐变/阴影/缓动/间距）
    fonts.css           # @font-face 自托管字体
    ThemeContext.tsx    # 明暗模式 + localStorage 持久化
  layout/
    AppShell.tsx        # 侧边栏 + 顶栏 + 内容区
    Sidebar.tsx
    TopBar.tsx
    CommandPalette.tsx  # ⌘K
  features/
    dashboard/
      DashboardView.tsx
      widgets/KpiCards.tsx / ConversionFunnel.tsx /
              RemindersSummary.tsx / MomentumChart.tsx / UpcomingSchedule.tsx
    reminders/
      RemindersView.tsx
  lib/
    insights.ts         # 纯函数：KPI/漏斗/响应率/动量/提醒派生
  components/…          # 现有组件（视觉对齐）
  App.tsx               # 精简为渲染 AppShell + 视图分发 + 全局 Modal
```

- 设计原则：`insights.ts` 全为纯函数（输入 apps/events/offers + now，输出结构化数据），与 UI 解耦、便于独立验证。widget 只负责渲染。

---

## 9. 状态 / 响应式 / 无障碍

- **空 / 加载 / 错误**：每个数据视图三态齐全——骨架屏（加载）、引导 CTA（空）、重试按钮（错误）。
- **响应式**：侧边栏三档（全宽 / 图标轨 / 抽屉）；驾驶舱网格在窄屏回落单列；看板已有移动端适配，保持。
- **无障碍**：导航项 `aria-current`、可见 focus ring、⌘K 全键盘可用、对比度达标、数字用 tabular-nums。

---

## 10. 验证

项目当前无测试框架（`package.json` 无 test 脚本）。本次验证以下述为准，不引入测试框架（避免 scope 蔓延）：

1. `npm run build`（`tsc -b && vite build`）类型检查 + 构建通过。
2. `npm run dev` 手动走查：明/暗模式、7 个视图、驾驶舱各 widget、提醒规则（造数据验证三类规则与计数）、响应式三档。
3. `insights.ts` 保持纯函数，为将来补单测留出口（本次不写）。

---

## 11. 分期建议（供 writing-plans 细化）

1. **设计系统地基**：fonts / tokens.css / antdTheme / ThemeContext + main.tsx 接入（明暗可切）。
2. **应用外壳**：AppShell / Sidebar / TopBar，把现有 7 视图挂进去（先不含新页），删旧 Header+Segmented+Statistic。
3. **insights.ts** 纯函数 + 提醒中心页面。
4. **驾驶舱主页** 各 widget。
5. **命令面板 ⌘K** + 简历匹配/AI 入口归并。
6. **现有视图视觉对齐**（Kanban CSS 等）+ 空/加载/错误态 + 微交互动效。
7. 构建 + 走查收尾。
