# 下一步建议 UX 收口设计

## 1. 目标与边界

本切片只收敛现有产品入口，不新增 AI 决策能力、API、数据库表或业务写入。目标路径为：

`简历 → 岗位 → 匹配评估 → 材料 → 面试准备 / 模拟面试 → 复盘沉淀 → Offer`

工作台与投递详情展示同一投递的只读“下一步建议”。建议由前端根据已加载的现有事实派生，说明“可以做什么”和“为什么现在建议”，并导航至已有入口。用户可以暂时收起或忽略建议，但这两种状态只存在于本次前端会话，不代表业务决定。

本切片明确不做：

- 匹配分、录用判断、自动状态推进或自动投递；
- 自动调用 AI、自动打开 AI 对话、自动生成材料或 Proposal；
- 创建或修改材料包、复盘草稿、Knowledge、Question、Reminder、Memory 或 Offer；
- 新建冻结快照或把当前输入宣称为冻结来源；
- URL 抓取、招聘平台访问和跨领域 handoff 写入。

## 2. 当前代码事实与复用边界

当前前端已有以下事实源和入口，应在本切片中复用，不复制一套规则：

| 用途 | 当前代码事实源/入口 | 本切片使用方式 |
| --- | --- | --- |
| 工作台投递和健康概览 | `web/src/layout/AppShell.tsx`、`web/src/lib/missionControl.ts` | 在工作台的投递区域挂载只读建议，使用 AppShell 已加载的 Application、Event、Material Kit 和练习统计 |
| 行动规则 | `web/src/lib/pipelineInsights.ts`、`web/src/lib/actionItems.ts`、`web/src/lib/actionHints.ts` | 不直接复用会产生重复卡片的展示层；抽取本切片需要的最小事实判断，保证同一纯函数被工作台与详情调用 |
| 投递详情 | `web/src/components/ApplicationDetail.tsx` | 展示同一份建议；点击只调用现有详情、Pilot 或面试索引导航回调 |
| 岗位评估 | `web/src/features/pilot/PilotOpportunityFitV2Card.tsx`、`web/src/layout/AppShell.tsx` | 仅导航到已有 Pilot/评估入口，不自动启动 Triage |
| 材料 | `web/src/components/MaterialKitDrawer.tsx`、`web/src/features/pilot/materialKitHandoff.ts` | 建议卡不得写入 handoff；只导航到投递详情，让用户自行打开材料包并确认预填 |
| 面试索引 | `web/src/components/InterviewV01View.tsx` | 使用事件上下文导航；多个事件不得由规则函数替用户选择 |
| 面试准备与模拟面试 | `web/src/components/InterviewPreparationProposalDrawer.tsx`、`web/src/components/MockInterviewDrawer.tsx` | 统一显示为“为该面试做准备”，进入事件入口后由用户选择准备建议或模拟练习 |
| 历史来源状态 | 现有各 Proposal/Review 的 `source_status` 或等价历史字段 | 只读展示为来源风险，不改变当前草稿和不触发重新生成 |

若现有页面尚未把某个事实传给组件，应在 AppShell 中沿用已存在的数据加载结果向下传递；不得为建议卡增加写 API 或新的数据模型。

## 3. 建议领域结构

新增前端纯类型与派生函数，建议放在：

`web/src/lib/nextStepSuggestions.ts`

规则函数接收当前已加载事实和当前时间，返回完整候选项与来源风险；组件只按展示策略渲染一个主行动和一个风险提示。

```ts
type NextStepDestination = {
  kind:
    | 'application_detail'
    | 'pilot_opportunity_fit'
    | 'material_kit_entry'
    | 'interview_event'
    | 'interview_review';
  applicationId: number;
  eventId?: number;
  reviewId?: number;
};

type NextStepSource = {
  label: string;
  status: 'current' | 'frozen' | 'changed';
};

type NextStepCandidate = {
  id: string;
  stateKey: string;
  title: string;
  reason: string;
  destination: NextStepDestination;
  sources: NextStepSource[];
};

type SourceRiskNotice = {
  id: string;
  stateKey: string;
  title: string;
  reason: string;
  sources: NextStepSource[];
};

type NextStepSuggestions = {
  candidates: NextStepCandidate[];
  sourceRisks: SourceRiskNotice[];
};
```

`applicationId` 始终必填；事件建议必须携带 `eventId`，历史评估建议必须携带 `reviewId`。禁止只用 `kind='interview'` 或页面当前选中项推断目标上下文。

## 4. 派生规则

### 4.1 行动建议与来源风险分离

行动候选和来源风险是两个独立集合：

- 行动候选回答“用户现在可以做什么”；
- 来源风险回答“已有冻结产物是否仍可直接作为当前依据”。

`source_changed` 只进入 `sourceRisks`，始终可见，不受“稍后处理”或“忽略”影响，也不能被主行动覆盖。可以将多个来源变化合并为一个风险提示，但必须列出每个变化来源及其只读入口。

### 4.2 行动候选生成顺序

候选顺序只用于选出一个主行动，不把不同阶段堆成多个流程卡：

1. 没有可用的当前 Resume：建议选择简历；来源标记为“当前使用来源”，不写“已冻结”。
2. 没有非空 JD：建议补充岗位 JD；只使用“当前岗位输入”文案，不把当前 JD 标为冻结。
3. 没有可查看的匹配评估：建议进入岗位评估；目标为 `pilot_opportunity_fit`，携带 `applicationId`。
4. 没有当前投递材料状态：建议准备投递材料；目标为 `material_kit_entry`，携带 `applicationId`，点击不得写入 `materialKitHandoff`。
5. 存在当前或未来的已排期面试事件：建议“为该面试做准备”；目标为 `interview_event`，携带 `applicationId + eventId`。准备建议和模拟面试是该事件下的两个可选路径，不拆成两个必做卡片。
6. 只有已结束的面试事件时：建议查看面试复盘或从已完成复盘沉淀知识；目标为 `interview_review`，携带 `applicationId + eventId`，且不把未完成事件引导到复盘。

当更早的条件成立时，后续候选仍可由函数返回，供测试和未来入口使用；展示组件只显示按上述顺序的第一条主行动。没有候选时显示中文空状态，不伪造下一步。

### 4.3 面试事件范围与排序

只有 `event_type='interview'`、当前投递可见且有 `scheduled_at` 的事件可以进入面试准备建议：

- 当前事件：当前时间处于 `scheduled_at` 到 `scheduled_at + duration_minutes` 的区间；没有时长时，按未结束事件处理并只允许进入事件入口；
- 未来事件：`scheduled_at` 晚于当前时间；
- 已结束事件：不进入准备建议，进入复盘/知识沉淀候选；
- 软删除投递或不可见事件：不生成候选；详情/深链的 404 仍由既有上下文清理逻辑处理。

多个当前或未来事件按 `scheduled_at ASC` 排序，同一时间按 `created_at DESC`、`id DESC` 排序。规则函数不得自动选择其中一个事件；主行动显示“选择面试事件”，点击进入带 `applicationId` 的事件索引，或调用已有事件选择入口。只有用户明确选择后，才生成带具体 `eventId` 的后续导航。

已结束事件按 `scheduled_at DESC`、`created_at DESC`、`id DESC` 排序，作为复盘/知识沉淀候选，同样不能跨事件猜测归属。

### 4.4 来源标签

- 当前 Resume、JD、事件：`status='current'`，固定标签为“当前使用来源”；
- Proposal、Review、Material Kit 或已确认 Knowledge 的冻结输入：只有现有记录明确提供冻结来源时才用 `status='frozen'`，标签为“已冻结来源”；
- 历史来源变化：`status='changed'`，标签为“来源已变化”；
- Resume、JD、事件的动态正文、公司名、职位名和证据摘录保留原文，不做翻译或摘要改写。

规则函数不得根据“存在一条记录”推断冻结；必须读取现有状态字段或现有历史响应中的来源信息。

## 5. 展示策略与会话状态

新增复用组件，建议放在：

`web/src/components/NextStepSuggestions.tsx`

组件展示顺序固定为：

1. 一个主行动：标题、理由、来源标签和“前往”按钮；
2. 一个来源风险区域：有风险时始终展示，无风险时不占用主行动位置；
3. “稍后处理”折叠区：包含已稍后的主行动，可恢复；
4. “忽略”不进入可见列表，但本次会话仍保留其状态，直到状态键变化或页面刷新。

“稍后处理”和“忽略”都不调用 API、不改变投递状态、不写入 localStorage、不改变 Proposal/Review/Material Kit，也不触发 handoff。刷新页面时两者均恢复显示。

会话状态由 AppShell 持有并按 `applicationId + suggestionId` 管理，工作台与投递详情共享同一状态。每个建议的 `stateKey` 必须至少包含：

`applicationId + suggestionId + destination context + current resume identity + JD presence/version + event identity/status + relevant frozen source status`

当来源状态、目标事件或当前简历/JD 版本变化时，生成新的 `stateKey`，旧的稍后/忽略状态不再适用。状态只影响当前显示，不构成用户的业务决定。

## 6. 导航与安全约束

点击主行动只调用现有导航回调，并携带完整上下文：

- 岗位评估：`applicationId`；
- 材料入口：`applicationId`，不传递或写入新的 handoff；
- 面试入口：`applicationId + eventId`；
- 历史复盘：`applicationId + eventId`，必要时再携带 `reviewId`。

建议组件不得直接调用 `axios.post/put/delete`、Proposal 生成 service、Material Kit handoff writer、Mock Interview start、复盘确认或 Knowledge 写入。用户到达现有入口后，仍必须通过原有确认和人工确认流程完成后续动作。

错误、404、来源变化和结果未知由目标页面的现有中文安全映射负责；建议组件只显示导航失败的固定中文兜底，不透传 Axios、服务端或模型原文。

## 7. 测试设计

测试只覆盖前端派生和导航，不新增后端 API 测试：

- `web/src/lib/nextStepSuggestions.test.ts`：无 Resume、无 JD、已有评估、已有材料、当前/未来面试、已结束面试、多个事件排序、软删除/不可见事件、来源变化独立输出；
- `web/src/components/NextStepSuggestions.test.tsx`：只渲染一个主行动和一个来源风险；稍后进入折叠区、忽略隐藏、恢复可见；状态键变化重置旧状态；动态 JD/职位名/证据原文不被翻译；
- `web/src/layout/AppShell.nextStepSuggestions.test.tsx`：工作台和详情使用同一派生规则；点击导航携带正确 `applicationId/eventId/reviewId`；多个事件不自动选择；
- 现有 `ApplicationDetail`、`AppShell` 和 `InterviewV01View` 入口测试：点击建议只调用导航 mock，所有 API 写 service 的调用次数保持为零；
- `web/src/layout/workspaceDrilldown.test.tsx` 或等价现有门禁：固定文案中文化边界，不禁止英文用户数据、JD、简历和证据摘录。

验收命令：

```powershell
Set-Location web
npm.cmd test -- --run src/lib/nextStepSuggestions.test.ts src/components/NextStepSuggestions.test.tsx src/layout/AppShell.nextStepSuggestions.test.tsx
npm.cmd test -- --run
npm.cmd run build
```

本切片不替代发布门禁。完成实现后仍需按当前分支既定流程执行后端分组门禁、`local`/`real-AI verify` 和浏览器主路径验收；真实 AI 只允许有界新尝试，不改变证据门控。

## 8. 风险与回滚

- 风险：不同页面加载的数据集合不完整，导致候选不一致。缓解：所有展示都调用同一纯函数，并对缺失事实使用显式 `unknown`，不能猜测为已完成。
- 风险：导航回调携带上下文不足。缓解：所有事件/历史目标在类型层要求对应 ID，测试断言完整参数。
- 风险：用户把提示误解为系统决定。缓解：使用“你可以”“建议现在”文案，保留“稍后处理/忽略”，不写“必须”“接受”“放弃”或录用判断。
- 风险：误触发跨流程写入。缓解：组件无写 service 依赖，导航测试对写调用做零调用断言。

回滚只需移除工作台/投递详情的建议组件挂载和会话状态，不涉及数据库、迁移、API 或用户数据。
