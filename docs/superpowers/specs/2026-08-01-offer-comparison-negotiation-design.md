# Offer 事实比较与谈薪准备设计

**基线：** `main@9ee97a8`
**设计状态：** 已完成用户确认，尚未进入实施。

## 1. 目标

OfferPilot 已具备 Offer 录入、横向事实比较和谈薪教练入口，但当前比较只能呈现固定字段，谈薪又容易脱离具体 Offer 上下文。本设计将两项能力收口为同一模块中的两条可选路径：

1. 用户可以先比较多个 Offer 的已知事实与自己关心的维度；
2. 用户也可以不比较，直接针对一个已选 Offer 准备谈薪；
3. 比较不替用户做决定，谈薪准备不替用户接受、拒绝或承诺任何 Offer。

该设计借鉴了职业工作区将比较、准备和历史放在同一事实上下文中的优点，但保留 OfferPilot 的本地优先、证据可追溯、人工确认与不自动执行边界。

## 2. 产品边界

- Offer 比较是用户录入事实和个人看法的并排查看工具，不生成总分、权重、排名、最佳 Offer 或接受/拒绝建议。
- 单 Offer 谈薪是独立路径，不要求用户先比较两个 Offer。
- 用户可以创建工作区级自定义比较维度，例如“通勤”“成长空间”“团队”“工作方式”；每个 Offer 仅保存用户自己填写的文字内容。
- 空白值只表示“尚未填写”，不表示负面、不构成系统推断。
- AI 仅在用户明确点击生成、确认输入快照后才调用；输出只是可编辑草稿，确认保存前不成为用户的准备记录。
- 不访问招聘平台、薪酬网站、法律网站或其他外部 URL；不将用户输入伪装成外部验证事实。
- 不新增 `offer_id` 作为 Chat 会话上下文字段。已关联投递的谈薪对话继续使用 `context_type=application` 与 `context_ref=<application_id>`；未关联投递的谈薪对话使用工作区上下文。

## 3. 当前事实与改造范围

当前模块已有：

- `offers` 的 CRUD、与 Application 的可选关联、固定薪酬字段和派生 `total_cash`；
- `GET /api/offers/compare?ids=` 对两个及以上可见 Offer 的顺序保持比较；
- Offer 中心、Offer 卡片、编辑表单和比较抽屉；
- Chat 的 `nego_coach` 模式，但持久化会话上下文仍是 application 或 workspace。

本期新增：

- 用户定义的比较维度和值；
- 以单个 Offer 为输入的、证据门控的谈薪准备 Proposal 与用户确认后的 Brief；
- Offer 中心的直接谈薪入口、比较入口和对应历史；
- Pilot 的静态 Offer 上下文卡与同一谈薪入口。

本期不改动投递详情的信息架构，不将 Offer 比较或谈薪面板塞入投递详情。投递详情仍只管理投递事实；Offer 中心负责 Offer 比较和谈薪准备。

## 4. 数据模型与历史语义

### 4.1 自定义比较维度

新增以下持久化模型：

```text
offer_comparison_dimensions
  id, label, archived_at, created_at, updated_at

offer_comparison_values
  id, offer_id, dimension_id, value_text, created_at, updated_at
  UNIQUE(offer_id, dimension_id)
```

- 维度名称为工作区级、用户定义的原文；显示和比较时保留原文，不由 AI 翻译或归类。
- `value_text` 是用户文本，不支持数值评分、星级、权重或自动色阶。
- 归档维度不再出现在新比较的默认列中，但旧值与历史 Brief 的快照保持可读。
- 删除 Offer 后，不删除已确认谈薪 Brief；历史记录保存原 `offer_id` 这个普通整数标识及冻结快照，并显示“来源已变化”。比较维度和值可按 Offer 清理。

### 4.2 谈薪准备 Proposal 与 Brief

```text
offer_negotiation_proposals
  id, offer_id, application_id, idempotency_key, attempt_status,
  source_fingerprint, input_snapshot, proposal_json, proposal_hash,
  source_states, lease_token, lease_expires_at, revision,
  invalidation_reason, created_at, ready_at

offer_negotiation_briefs
  id, proposal_id, offer_id, origin_application_id,
  selected_blocks_json, edited_content_json, confirmed_at
  UNIQUE(proposal_id)
```

- `input_snapshot` 冻结：Offer 固定字段、用户自定义维度和值、本次用户填写的谈薪目标/顾虑/沟通场景；不包含外部数据、Chat 原始全量记录或无关投递数据。
- `source_fingerprint` 是规范化快照的哈希；`proposal_hash` 是规范化 Proposal 的哈希。原文不进入日志、幂等键或 UI 状态键。
- 相同幂等键与相同指纹稳定重放已有 Proposal；相同键但不同指纹返回 `409 offer_negotiation_idempotency_conflict`，不覆盖原记录。
- Proposal 使用 `generating`、`provider_unknown`、`ready`、`invalidated` 状态与 SQLite lease/CAS。只有未完成状态可失效；`ready` Proposal 永远保留原快照。
- Provider/网络结果未知时保留原尝试和幂等键；确定的输入错误可清除前端草稿；契约失败落库严格安全空 Proposal，不展示模型原文。
- 用户确认后才创建唯一 Brief。再次确认同一 Proposal 返回已有 Brief，不能重复创建。
- 当前 Offer 被编辑或删除时，历史 Proposal/Brief 仍可读；读取时比对当前事实，返回 `source_changed`，但不自动改写、重新绑定或再生成。

## 5. 比较体验

### 5.1 单 Offer 直接路径

每张 Offer 卡都提供“开始谈薪准备”。点击后进入谈薪准备抽屉，用户填写：

- 本次沟通目标；
- 关心或担心的事项；
- 场景，例如电话沟通、邮件回复或 HR 面谈。

用户在确认调用前可完整查看将被使用的 Offer 事实和自定义维度。未绑定 Application 的 Offer 仍可使用该功能，但界面明确其谈薪对话属于工作区上下文。

### 5.2 多 Offer 比较

用户主动勾选至少两个不同、可见的 Offer 后，才能打开比较抽屉。比较按用户选中顺序保留列顺序，分为：

1. 固定事实：职位、状态、月薪、年薪月数、签约奖金、股权、福利、截止日期；
2. 用户自定义维度：每项并排列出原文或“尚未填写”；
3. 用户备注与待澄清信息。

比较页不出现汇总得分、默认排序、颜色优劣暗示、推荐结论或“最佳 Offer”。用户可以从任意列显式点击“用此 Offer 准备谈薪”，进入该 Offer 的单 Offer 路径。

## 6. 谈薪生成契约与人工确认

### 6.1 结构化草稿

用户确认 AI 调用后，Provider 仅接收冻结的 `input_snapshot`。输出使用严格 JSON，且拒绝重复 key、非有限值、额外字段、超限数组和不属于快照的证据引用：

```ts
type OfferNegotiationProposal = {
  proposal_status: 'normal' | 'safe_empty';
  communication_goals: ProposalItem[];
  clarification_questions: ProposalItem[];
  talking_points: ProposalItem[];
  preparation_checks: ProposalItem[];
};

type ProposalItem = {
  id: string;
  text: string;
  rationale: string;
  evidence_refs: Array<{
    source: 'offer_snapshot' | 'user_brief';
    path: string;
    excerpt: string;
  }>;
};
```

- 每个带有事实前提的条目必须引用 Offer 快照或本次用户输入中的准确路径和逐字摘录。
- 不依赖具体事实的澄清问题只能使用版本化固定 allowlist；一旦提及金额、截止日期、福利、股权或用户顾虑，仍必须有证据引用。
- 输出不得包含市场薪酬断言、法律意见、虚构政策、是否接受/拒绝 Offer、对其他 Offer 的优劣判断或替用户作出的承诺。
- 首次格式或结构失败可进行一次只含失败类别和允许路径的修复；伪造来源、非法路径、摘录不匹配、超限和语义越界不可修复。
- 两次可修复契约失败后，服务端生成并校验固定安全空 Proposal；Provider/网络异常返回安全 `502`，并保留原幂等键。

### 6.2 用户确认

谈薪准备抽屉以可编辑区块显示结果。用户可以选择要保存的区块并编辑文字；点击“确认保存”前不会创建 Brief、Chat 写入、提醒或任何外部动作。

保存时原子校验 Proposal、Offer、Application 归属和 `source_fingerprint`。如果当前来源变化，返回 `409 offer_negotiation_source_changed`，展示中文解释与只读历史，用户可以明确选择重新生成。确认后的 Brief 只读可查看，保留用户最终编辑内容及确认时间。

## 7. UI 与 Pilot 协作

### 7.1 Offer 中心

不改变 Offer 中心的页面职责或整体布局，只在现有 Offer 卡片、比较抽屉和新增谈薪准备抽屉中补充功能：

- Offer 卡片：查看/编辑、比较选择、“开始谈薪准备”、历史准备记录；
- 比较抽屉：事实、用户维度、缺失信息、从指定 Offer 开始谈薪；
- 谈薪准备抽屉：输入确认、来源说明、生成结果、编辑、确认保存、历史只读查看。

固定文案使用中文；公司、岗位、福利、用户维度、Offer 备注和 AI 可验证草稿均保留原文。

### 7.2 Pilot

Pilot 不自行推导 Offer 规则，也不自动发送消息。只有用户已打开 Pilot 且选中了明确 Offer 时，Offer 中心才向 Pilot 注入一张静态上下文卡，展示：Offer 名称、已知来源类型、可用操作“准备谈薪”。

- 用户未选择 Offer 时，Pilot 先列出可见 Offer 供用户明确选择；不猜测目标。
- 用户点击“准备谈薪”后，Pilot 展示同一份目标/顾虑/场景输入和来源确认；用户确认后才调用生成接口。
- 关联 Application 的 Chat 仍使用 `context_type=application`；没有关联 Application 的 Chat 使用工作区上下文。Offer ID 只能作为本次受控附件或准备 Proposal 的输入标识，不能变成 Chat 持久化上下文字段。
- Pilot 与 UI 调用同一生成、确认、历史读取 API；不会维护第二套 Prompt、状态机、重试或写入逻辑。

## 8. 安全、错误与状态语义

- Offer 不存在或当前不可见：新生成返回 `404`，前端清理确定失败草稿；历史 Brief 仍可按其独立 ID 只读查看并标记来源已变化。
- 输入缺失或非法：`422`，不创建 Attempt；前端清理该次草稿。
- 相同键不同快照、已失效 Attempt、来源漂移：稳定 `409`；不覆盖历史。
- Provider/网络、裸 `5xx`、响应丢失或超时：安全 `502`，前端显示“结果待确认”，冻结输入，仅允许使用原尝试重试。
- `202 generating/provider_unknown` 也保留原 key 和输入，前端轮询或由用户以同一请求重试；不得创建第二次 Provider 调用。
- 错误文案只按稳定错误码和 HTTP 状态映射为中文；禁止展示 Provider 原文、Axios message、服务端异常、Offer 快照或用户输入。
- 脱敏诊断仅记录失败类别、HTTP 状态、超时、耗时、修复次数和已哈希的 Provider request id。

## 9. 测试与真实验收

### 9.1 自动化测试

- 数据迁移：新库创建、旧库升级、唯一约束、Offer 删除后的历史快照、归档维度；
- API：Offer 可见性、比较至少两个不同 Offer、维度 CRUD、维度值、单 Offer 生成、快照指纹、幂等重放、lease/CAS、来源漂移、确认幂等；
- AI：严格 JSON、重复 key、非有限值、字段/数组上限、合法/伪造证据、一次修复、固定安全空、Provider 未知与脱敏日志；
- 前端：单 Offer 直接入口、多 Offer 比较、用户维度、无评分/无推荐文案、确认前零 Brief 写入、来源变化、未知结果重试、历史只读、Pilot 选择与上下文；
- 安全：不访问招聘平台或外部数据源；Pilot/UI 都不能绕过确认；Chat 不新增 `offer_id` 上下文字段。

### 9.2 隔离真实 AI 与浏览器验收

使用现有配置的副本和临时 `OFFERPILOT_DATA`，用中文案例完成：

1. 创建至少两个中文 Offer，补充“通勤”“成长空间”等用户维度；
2. 在比较抽屉查看事实和缺失项，确认无评分、排名或建议接受/拒绝；
3. 从一个 Offer 直接进入谈薪准备，填写中文目标、顾虑和场景；
4. 明确确认 AI 调用，验证结构化草稿中的引用来自冻结 Offer/用户输入；
5. 编辑并确认保存 Brief，关闭重开后验证历史、来源状态和内容；
6. 通过 Pilot 选择同一 Offer，验证其入口、确认和 UI 路径共享同一上下文；
7. 记录本地 `/api` 请求和服务端受控 Provider endpoint，确认无招聘平台访问；停服后清理合成 Offer、维度、Proposal、Brief、Chat 记录和临时目录。

## 10. 实施顺序

1. 审查现有 Offer、Chat、Agent 与 Compare API，完成迁移和后端领域契约；
2. 先以测试驱动完成维度、快照、Proposal、Brief、幂等与来源变化；
3. 再接入 Offer 中心的单 Offer、比较与历史 UI；
4. 最后接入 Pilot 的静态卡和同一 API 路径；
5. 运行分组后端门禁、前端全量、构建、local/real-AI verify 与隔离浏览器验收；
6. 完成独立代码复审后，再讨论合并。

本设计不继续实现或修改 `feat/20260801-application-journey` 分支中的投递详情旅程面板。该方向因会与投递详情的管理职责冲突而停止。
