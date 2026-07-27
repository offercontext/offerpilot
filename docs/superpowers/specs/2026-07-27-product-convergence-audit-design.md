# OfferPilot 产品收敛审计与设计

**日期**：2026-07-27
**基线**：当前分支 `602f6b8` 及其 `origin/main` 祖先
**本轮范围**：只记录事实、收敛设计和后续验收，不改业务代码、API、数据库或测试。

## 1. 审计口径

本审计以当前 React 入口、FastAPI 路由、repository、测试和已有隔离浏览器验收为事实；主 Wiki 与本地架构/发布文档只用于标记一致性，不用旧路线图推断“已实现”。状态含义为：`正式可用`= 有用户入口和可验证闭环；`隐藏可用`= 只能从详情/Pilot 等上下文进入；`占位`= 有入口但不承载正式数据；`未挂载`= 后端/组件地基存在但没有稳定产品入口；`已废弃候选`= 现状与收敛边界冲突，等待移除或隐藏。

## 2. 能力审计矩阵

| 能力 | 用户目标与自然入口；实际入口/可发现性/恢复 | 数据与证据；写入与确认 | 外部动作 | 状态；代码/测试/真实证据 | Wiki/本地文档一致性与问题分类 |
|---|---|---|---|---|---|
| 投递 | 记录岗位并推进状态；左栏“投递”、看板/列表/日历，详情可恢复 | Application、JD 文本、事件、Resume/Material Kit；手工 CRUD 和状态变更，Chat 写操作有 pending 确认 | 现有 `jd_url` 分析路径会抓取 URL，属于已存在缺陷 | 正式可用；`ApplicationDetail.tsx`、`api.py` applications/events、`tests/test_applications_api.py`、本地浏览器投递走查 | Wiki 投递 P0/P1 基本一致；URL 仅记录的收敛要求与当前 `/api/jd/analyze` 不一致（缺陷） |
| 材料包 | 为一条投递准备材料；详情“材料包”，Pilot 交接后打开 `MaterialKitDrawer`，可恢复冻结预填 | Material Kit 关联 Resume/JD；Proposal 使用 Resume/Kit/Evidence Bundle/用户断言，逐项人工接受才派生 Resume，来源漂移 `409` | 不访问招聘平台，不自动投递 | 正式可用；`material_proposals.py`、`material_revision_proposals.py`、`MaterialKitDrawer.tsx`、相关 AI/API 测试；已有本地/真实 Provider 验收 | Wiki 将 material_kit 列为 v0.2，代码已提前可用；应以当前证据门控行为为实现事实（文档滞后） |
| 机会评估 | 判断是否值得继续准备；投递详情“岗位评估”或绑定 Application 的 Pilot | 冻结 JD、Resume、用户断言；Triage/Deep Review 写不可变评估，人工确认 Triage/Deep，材料交接仍手动 | 不抓 URL、不访问招聘平台、不改投递状态 | 正式可用但主要隐藏在详情/Pilot；`opportunity_fit_reviews.py`、`PilotOpportunityFitCard.tsx`、`AppShell.tsx`、`tests/test_opportunity_fit_reviews*.py`、Pilot 前端专项与真实浏览器走查 | Wiki 的“Pilot 建议/投递辅助”方向一致；当前实现比旧 MVP 规划更具体，历史文案需收敛 |
| 面试复盘 | 绑定面试事件记录复盘并查看可审阅建议；投递详情的 interview 事件/复盘入口 | InterviewNote、同投递 interview event；保存复盘是手工写入，生成 Proposal 需确认，建议逐条引用复盘快照；来源变化保留历史只读 | 无 | 隐藏可用，顶层面试仍占位；`notes.py`、`interview_review_proposals.py`、`InterviewReviewProposalDrawer.tsx`、`ReviewManagementView`，后端/前端专项已覆盖 404/409/502/来源漂移 | Wiki 仍把正式笔记列为 v0.2；当前已有内部闭环，顶层入口与文档不一致（文档滞后） |
| 面试知识沉淀 | 从复盘选原始片段，确认后形成可审计 Knowledge；复盘入口的 capture drawer/知识库 | 只能选 interview_note 原始片段；可选 AI 预览，确认事务创建 Captured Source/Evidence/Note Version；取消/未确认不写入，不能自动生成题目/Memory | 无 | 隐藏可用；`interview_knowledge_capture.py`、`InterviewKnowledgeCaptureDrawer.tsx`、`knowledge-system.md`，后端专项和隔离真实调用已验证安全空结果/审计保留 | 与 Knowledge 架构 `Captured Source → Evidence → Note Version` 一致；主 Wiki 仍把自动沉淀列为后置，代码已提供受控人工路径，需明确不是自动沉淀 |
| 面试准备 | 围绕已安排面试准备；投递详情 interview 事件“面试准备建议”，也可由 Pilot 引导 | 当前事件、冻结 JD、选定 Resume、用户选定 Knowledge Evidence；用户断言保存在快照但不发送 Provider；Proposal 只读查看/复制，生成非自动写入 | 无 | 隐藏可用；`interview_preparation_proposals.py`、`InterviewPreparationProposalDrawer.tsx`、`ApplicationDetail.tsx`、AI/repository/API/smoke 测试；已有隔离真实 Provider 浏览器闭环 | Wiki 将面试前简报/复习列为后置；当前是证据门控的受控实现，文档需标为超前但不扩大范围 |
| Knowledge | 浏览来源、Evidence、确认笔记并供受控消费者查看；左栏“知识库” | Imported/Captured Source、Evidence、Note Version；普通导入和人工确认写入，已确认 interview source 只读，Brief 自动链路按 ADR 禁用 | URL/网页抓取不是本轮入口；导入是用户主动提供原文 | 正式可用（V1 Source/Evidence 基础）；`KnowledgeSourcesView.tsx`、`src/offerpilot/knowledge/*`、`knowledge-system.md`、Knowledge V1 acceptance 测试 | 与 `docs/architecture/knowledge-system.md`、ADR-0003/0004 基本一致；主 Wiki 的 Wiki/自动总结/Memory 规划仍是后续，不得当作当前能力 |
| Pilot | 在当前 Application/页面上下文中得到建议并发起受控流程；左栏 Pilot、业务页右侧 Pilot | 会话、上下文附件、结构化评估草稿、pending tool action；读操作直接执行，写操作应逐次人工确认 | 工具白名单限制本地数据；不允许招聘平台访问 | 正式可用；`AppShell.tsx`、`features/pilot/*`、`ai/agent.py`、`repositories/chat.py`、`tests/test_chat*.py`、Pilot 浏览器走查 | 主 Wiki 的“双形态 Pilot、上下文和审批卡”一致；写操作 `auto_approve` 分支仍是 P0 收紧对象（缺陷） |
| Offer | 记录并查看 Offer；投递模块 Offer 中心，详情/Command Palette 可达 | Offer 的公司、职位、手工金额、周期、签字费、权益/福利/截止期；手工保存，无 AI 自动写入 | 无 | 正式可用；`OfferCenterView.tsx`、`AddOfferForm.tsx`、`OfferCompareDrawer.tsx`、`repositories/offers.py`、Offer API/前端测试；比较安全性尚未达收敛门槛 | Wiki 将 Offer 中心列为 v0.2，入口一致；当前比较按钮允许少于两个且后端无口径校验（缺陷） |
| 谈薪 | 用户希望基于已确认 Offer 准备沟通；当前无独立谈薪入口或稳定 API | 现有 Offer 的 `notes/assessment` 不是谈薪工作流，也不应被解释成 AI 谈判结论 | 不外联、不代发 | 未挂载；仅见 Offer 字段和旧路线图，未见当前专用组件/服务/测试 | 主 Wiki/子 PRD 将谈薪放 v0.3；本轮明确延后，不把旧规划当已实现 |
| Dashboard/Reminders | 了解今日行动和截止期；首页 Dashboard、左栏提醒、Command Palette | 从 Application/Event/Offer/Material Kit/题库统计派生；点击进入业务页，当前不直接写域数据 | 无 | 正式可用但规则事实源分散风险；`DashboardView.tsx`、`RemindersView.tsx`、`lib/missionControl.ts`、`lib/pipelineInsights.ts`、对应前端测试/静态 smoke | Wiki 要求今日行动/提醒；代码已有实现，命令面板仍有静态提示，规则统一属于 P1 收敛 |
| Chat Agent | 在 Pilot 中问当前问题、查看证据并请求动作；Pilot tab、右侧栏、Command Palette | Conversation、附件、工具调用和 pending confirmation；当前有 `auto_approve` 配置路径，必须收紧写操作 | 仅已注册白名单工具；不允许任意 shell/招聘平台 | 正式可用（写入确认需收紧）；`ai/agent.py`、`repositories/chat.py`、Chat API/前端测试、已有 Pilot 浏览器验收 | 主 Wiki 的工具/审批/会话恢复一致；自动确认与“每次写操作确认”冲突（缺陷） |

**事实结论分类**：面试顶层占位、URL 抓取入口、Offer 不足数据仍比较、Chat/Agent 自动确认是“已存在缺陷”；面试相关能力只在详情/Pilot 可达、主 Wiki 版本表未更新是“文档滞后”；谈薪、模拟面试、自动 Brief/Memory 扩张及外部平台能力是“明确延后/未挂载”，不能以旧入口或死代码宣称已完成。

## 3. P0 收敛设计

### 3.1 决策权与输出语义

所有 AI 面向用户的结论统一为“证据、条件、风险、待确认问题、可选下一步”。输出必须标明来源和来源状态；无法验证时返回固定中文安全空结果或“资料不足”，不返回分数、通过率、录用/放弃建议。产品层禁用将 `accept/reject/withdraw` 作为模型最终裁决；这些词若来自用户数据或历史原文仍原样展示，但不作为系统动作。任何 Application、Event、Resume、Material Kit、Offer 状态变化都只能由用户明确操作触发。

后续改动采用最小增量契约：保留现有 Proposal JSON/API 字段，先在各入口做展示适配和校验；确需新增时只增加 `evidence_refs`、`conditions`、`risks`、`questions`、`next_step` 等可选结构，旧快照按旧 schema 只读，不回写重解释。错误码稳定映射为中文：来源冲突 `409`、输入/绑定不满足 `422`、资源不可见 `404`、Provider/网络结果未知 `502`、不可验证安全空结果 `201`；原始 Axios、Provider、模型文本不透传。

### 3.2 Agent 写入与人工确认

读取、分析和生成 Proposal 不等于写入。所有 Agent 触发的新增、更新、归档、删除、状态迁移和批量动作都先持久化为带资源摘要、参数、证据、过期时间和一次性确认 token 的 pending action；用户逐次确认后才 CAS 执行，资源已变化返回安全 `409` 并保留原记录。拒绝、取消和过期不得落库。删除或收紧现有 `auto_approve`：模型/会话/Provider 配置都不能使写操作跳过确认；手工点击保存、编辑、删除仍走原生确认和表单，不被 Agent gate 阻塞。回归范围覆盖 Chat API、确认消费一次、并发确认、过期 token、失败不写入和所有写工具注册表。

### 3.3 面试顶层入口

将顶层 `InterviewV01View` 从空状态/本地占位改为真实索引：列出当前可见 Application 的 interview events、已绑定 notes、复盘 Proposal、已确认 Knowledge 和可用的面试准备入口；点击后回到投递详情或专用只读抽屉，按现有冻结快照恢复。`ReviewManagementView`、知识沉淀和面试准备作为已实现能力正式挂载；它们的生成仍需用户确认。当前没有稳定闭环的 Mock/模拟面试入口保持隐藏，并列为独立产品化设计或移除候选，不允许通过旧组件/死路由半可达。事件/投递软删除统一 `404`、清理上下文、禁止 handoff；历史 Proposal 在 note/event 来源变化时仍只读可审计。

迁移兼容：索引优先复用现有 Application/Event/Note/Proposal API，不新增表；查询只加可见性和分页组合。旧 `interview_notes`、mock 数据不删除，未挂载 Mock 不被新入口引用。前端影响是新增索引和恢复态，后端影响是聚合读取/安全错误映射，现有详情入口和手工复盘保存语义不变。

### 3.4 Offer 对比安全性

比较状态固定为：少于两个有效 Offer=`not_enough_offers`；币种、计薪周期、金额口径任一缺失或不一致=`not_comparable`；字段完整且一致才=`comparable`。前端按钮与后端 `/api/offers/compare` 同时拒绝前两种状态，不能只依赖 UI。金额只接受用户手工记录的非负数、明确计薪周期和币种；没有这些字段的旧 Offer 只能展示原值，不能参与平均值、排名或总包换算。禁止税后推算、权益估值、风险调整和“最优 Offer”裁决；最多提供逐字段并列查看与“需用户确认口径”的提示。

迁移兼容：不重写历史金额、不猜测币种/周期；若后续需要字段，新增 nullable 字段，旧数据进入 `not_comparable`。回归覆盖 0/1/2 个 Offer、混币种、混周期、缺字段、负数/小数边界、删除后比较和 API 绕过前端。

## 4. P1 收敛设计

### 4.1 行动提示的单一规则事实源

以一个纯函数规则层作为 Dashboard、Reminders、Command Palette 和 Pilot 只读行动卡的共同来源；输入明确列出 Application 状态/更新时间、未来 Event 时间、Offer deadline、Material Kit 完整度、题库到期统计和当前时间。每条 `ActionHint` 必须携带稳定 id、原因、触发输入摘要、阈值、优先级、目标入口和是否需用户确认；不允许组件各自写“临近/停滞/到期”条件。当前 `derivePipelineInsights`/`deriveMissionControl` 先由测试锁定行为，再让三个入口消费同一结果；Command Palette 的静态快捷命令仍可保留，但不得伪装成动态提醒。回归覆盖时区、边界秒、软删除、重复提示、点击恢复和无数据空状态。

### 4.2 五类证据门控 AI Proposal 一致性矩阵

| 流程 | 允许输入/证据 | 结果与人工边界 | 漂移/未知/失败 |
|---|---|---|---|
| 材料 Proposal | 冻结 Application、Material Kit、Resume、可选 Evidence Bundle/用户断言；引用必须逐字命中允许路径 | 变更逐项审阅；接受才派生 Resume 并更新 Kit | Resume/JD/Kit 漂移 `409`；Provider 未知保留 key；契约失败安全 `502/空结果` |
| 机会评估 | 当前可见 Application、用户选 Resume、原始 JD、用户断言；Triage/Deep 条目须有 JD/Resume/断言证据 | 只给条件、风险、问题和可选路径；材料交接仍由用户决定 | 历史只读；当前资源不可见 `404`；来源冲突 `409`；无证据不得通过 |
| 面试复盘建议 | 本次 InterviewNote 与 interview event 元数据；不读 JD/旧 AI/Memory | 观察、练习重点、澄清问题逐项引用复盘字段；不形成能力画像 | 编辑后旧快照 `source_changed`；Provider/网络未知保留 key；契约失败安全空 |
| 面试知识沉淀 | 用户选中的 note 原始片段；AI 仅可选可编辑预览 | 确认事务才建 Captured Source/Evidence/Note Version；AI 文本永远是派生成果 | 未确认可删除；未知保留 Attempt；已确认只读审计，禁止通用 Source/Brief 写入 |
| 面试准备建议 | interview event、冻结 JD、选定 Resume、显式选择的确认 Knowledge Evidence；用户断言不发 Provider | 只读准备方向/故事提示/复习点/问题/待确认事项，复制不写业务数据 | 同 key 快照冲突 `409`；lease/CAS 防双调用；`202` 冻结输入，Provider 未知保留 key，契约失败安全空 |

统一测试先于公共抽象：每类保留自己的输入白名单、证据路径和领域错误码；只抽取最小的 JSON 解析、非有限值/重复键、证据逐字校验、幂等/CAS 和安全诊断底层。不得用“大一统 Proposal”抹平不同的确认写入语义。

### 4.3 JD URL 与文案扫描

`job_url/jd_url` 的产品含义统一为用户记录的来源地址或备注；保存、展示、历史快照可保留字符串，但不因存在 URL 触发抓取、登录、解析、网络请求或平台动作。当前 `api.py` 的 `_fetch_text_from_url`/`/api/jd/analyze` 是已存在边界缺陷：收敛批次应移除主流程 URL 分支并覆盖旧入口负向测试；不扩大外部权限，也不迁移历史 URL。

固定中文扫描只检查受控系统短语和无障碍/加载/错误文案，例如 Proposal 标题、按钮、状态、证据来源标签和 Axios 错误兜底；测试用版本化 allowlist/denylist，不能扫描任意英文。JD、公司/职位、Resume 标题、用户断言、AI 正文和证据摘录保持原文。

## 5. 明确不做与后续依赖

本轮不加入 Offer 决策助手、模拟面试、语音/录音转写、外部招聘平台访问、自动投递、知识库自动扩张、长期 Memory/能力画像自动写入、提醒通知系统、税后或权益价值推断。谈薪与 Mock 只保留为后续独立设计依赖；自动 Brief、题库/练习自动生成也不由本轮收敛顺带启用。任何路线图条目都不能作为当前入口或事实源。

## 6. P0 → P1 实施顺序、风险与回归

1. **P0-A 事实和写权限收口**：先锁定 Agent 写工具与统一安全错误；风险是旧会话 pending 恢复和手工保存回归；覆盖 Chat/Agent API、确认 CAS、工具注册、全量写路由和浏览器 Pilot。
2. **P0-B 面试真实索引**：复用现有查询做顶层 index、详情恢复和 404 清理；风险是同一 note/Proposal 多入口状态分叉；覆盖软删除、历史来源变化、事件选择、知识/准备入口及手工复盘。
3. **P0-C Offer 比较门禁**：前后端共享可比性判断但不重算旧数据；风险是现有 Dashboard KPI 与 Offer 中心显示变化；覆盖 API/UI 0/1/2、口径不一致和旧字段兼容。
4. **P1-A 统一行动规则**：先为纯规则函数补边界测试，再接 Dashboard/Reminders/Command Palette；风险是提醒重复或时间区间变化；覆盖时区、阈值、导航、软删除。
5. **P1-B Proposal 一致性**：逐流程补负向/并发/来源漂移矩阵，再抽取最小公共校验；风险是错误码或安全空状态改变；覆盖五类后端、前端历史/未知重试、隔离 real-AI。
6. **P1-C URL/中文回归**：移除 URL 触发路径，扫描固定短语；风险是误伤用户英文数据或旧历史；覆盖网络请求白名单和动态原文保留。

最终门禁必须包括后端全量、前端全量/构建、静态 smoke、隔离 local verify 和真实 Provider 浏览器闭环；真实闭环只使用合成数据/临时数据目录，验证用户确认、无跨领域写入、无外部平台请求并清理残留。本设计阶段只完成文档审计，不执行上述实现测试。

## 7. 一致性结论与复审项

当前代码已经超出主 Wiki 的部分旧版本标记，尤其材料、机会评估、面试复盘/知识/准备；这是“实现先行、文档滞后”，不是新增路线图。Knowledge 的 Source/Evidence/Note Version 和自动 Brief 延后与本地架构文档一致。待复审确认的最小决策是：P0 先收紧 Agent 写权限、再把面试顶层索引产品化，并按本设计将 Mock/谈薪保持隐藏；通过后再另写测试先行计划，当前不进入代码调整。
