# 证据门控的事件级面试准备建议设计

- 任务：`feat: AI add evidence-gated interview preparation`
- 日期：2026-07-24
- 状态：待复审设计；本阶段只提交设计，不修改实现代码
- 基线：`origin/main`（`71a9de1`）

## 1. 目标与边界

### 1.1 目标

本功能围绕一场已经安排的面试，帮助用户准备下一步行动。用户在投递详情的面试事件或 Pilot 中明确选择本次输入，服务端冻结输入快照，再生成可审阅、可引用的面试准备建议。

建议只回答“基于当前资料可以准备什么”，不替用户判断是否匹配、是否能通过或是否应该继续投递。每一条具体建议必须能回到本次冻结的岗位描述、选定简历或用户明确选中的已确认 Knowledge Evidence。

### 1.2 非目标

- 不做匹配分、通过率、录用概率、Offer 决策或“是否值得参加”的判断。
- 不做模拟面试、录音、转写、自动生成题目或自动安排练习。
- 不读取旧的 AI 建议正文、完整旧复盘、聊天历史、长期 Memory 或隐式检索结果。
- 不自动创建或修改 Application、ApplicationEvent、Resume、Material Kit、Question、InterviewNote、Knowledge、Memory、提醒或投递状态。
- 不抓取 JD URL、公司网站或招聘平台，不访问外部招聘平台，不自动投递。
- 不将用户断言、模型建议或来源摘要伪装成简历事实、岗位事实或已确认 Knowledge Evidence。

本设计只新增面试准备建议的 Proposal 快照和对应的只读 API/界面，不改变既有事件、简历、Knowledge 或材料流程的数据语义。

## 2. 生成资格与用户确认

### 2.1 生成前置条件

只有以下条件同时满足，服务端才允许进入模型生成阶段：

1. Application 当前可见，`deleted_at IS NULL`，且属于当前用户可操作的投递上下文。
2. 请求显式指定一个 `event_id`；事件当前存在、属于该 Application、`event_type == "interview"`，且事件本身可见。
3. 请求显式指定一个当前可见的 `resume_id`；服务端读取该 Resume 的当前 `content_json`，不接受客户端上传的简历正文或指纹。
4. 请求带有用户确认使用的非空 `jd_text`。JD 只能来自用户粘贴或现有本地冻结 JD 的明确预填；服务端不接受 `job_url`，不调用任何 URL 抓取逻辑。
5. `knowledge_selections` 只包含用户明确选中的已确认 Knowledge Note/Evidence；可以为空，但服务端不得自动补充其他 Note、Evidence、FTS 结果、向量召回或相似内容。
6. 可选 `user_assertions` 通过数量和长度校验。它们在快照中独立标识，不能作为 Resume、JD 或 Knowledge Evidence 使用。

前置条件失败时不调用 Provider、不创建 Proposal，返回稳定的中文错误映射。缺少事件、简历或 JD 均使用 `422`，而 Application 软删除或不可见使用 `404`。客户端不能通过提供旧 Proposal 的字段、哈希或模型结果绕过这些检查。

### 2.2 用户确认的交互

入口位于：

- 投递详情的当前可见 `interview` 事件卡片；
- 已绑定该 Application 的 Pilot 上下文。

用户先选择简历、检查/粘贴 JD、选择零个或多个 Knowledge Evidence、填写可选断言，再看到固定中文确认提示：这些选定内容将发送给当前配置的 AI 服务。用户取消确认不发请求；只读查看历史不触发模型调用。

确认按钮只负责生成 Proposal，不触发任何下游写入。生成结果必须先由用户审阅；本首期没有“接受并改简历”“创建题目”“保存 Knowledge”或“改变投递状态”的按钮。

## 3. 输入快照与最小化发送

### 3.1 服务端构建的冻结快照

服务端在一个短 SQLite session 中读取并规范化以下值，然后关闭 session，才允许调用 Provider：

```json
{
  "schema_version": "interview-preparation-input-v1",
  "application_id": 12,
  "event": {
    "id": 34,
    "event_type": "interview",
    "subtype": "technical",
    "round": 2,
    "scheduled_at": "2026-07-30T09:00:00Z",
    "duration_minutes": 60,
    "status": "todo"
  },
  "jd": {"text": "用户确认的岗位描述原文", "sha256": "..."},
  "resume": {
    "id": 56,
    "title": "用户选择的简历标题",
    "content_json": {},
    "sha256": "..."
  },
  "knowledge_evidence": [],
  "user_assertions": []
}
```

快照中的 `application_id`、事件 ID、简历 ID 和 Knowledge ID 只用于审计、指纹与漂移检查；模型请求不得发送内部数据库 ID。事件只发送必要的面试上下文：`event_type`、`subtype`、轮次、开始时间、时长和状态。不得发送 `location`、事件备注、会议链接、联系人、Application 全对象或 `job_url`。

JD 使用用户确认的原文，不做 trim 以外的规范化；不读取 URL。Resume 只发送用户选定的这一份当前 `content_json`，不发送其他 Resume、文件路径或解析日志。Knowledge 只发送用户选中的 Evidence 原文与其冻结路径，不发送 Knowledge Note 的 AI/用户派生成文案、旧 Interview Review Proposal、Note 全文、Memory 或检索结果。

用户断言发送时保持独立的 `user_assertions` 数组。它们可以帮助模型识别用户希望补充的信息，但不能出现在 `evidence_refs` 中，也不能被描述为“简历证明”“岗位要求”或“已确认知识”。

### 3.2 输入限制与确定性规范化

输入上限固定如下，超过即 `422 interview_preparation_input_too_large`，不得静默截断：

- `jd_text`：最多 60,000 个 UTF-8 bytes，必须非空；
- Resume `content_json`：沿用现有 Resume JSON 合法性检查，序列化后最多 200,000 个 UTF-8 bytes；
- Knowledge：最多选择 5 个已确认 Note Version、最多 20 条 Evidence，总 Evidence 原文最多 64,000 个 UTF-8 bytes；
- `user_assertions`：最多 10 条，每条最多 500 个字符；空字符串过滤后再计数；
- `idempotency_key`：服务端生成格式校验，长度 16–128 个 ASCII 字符；
- 事件基本字段和每个 Evidence 的路径/摘录均必须是字符串或明确的整数，不接受任意 JSON 对象扩展。

Canonical JSON 使用 UTF-8、固定字段顺序、无额外空白、`ensure_ascii=false`；数组保持用户明确选择后的顺序，Knowledge Evidence 在快照中按 `(note_version_id, evidence_id)` 稳定排序。所有文本保持原始 Unicode，不做 NFC/NFD、大小写、空白或换行归一化。`source_fingerprint` 是该完整快照的 SHA-256；其变化必须可重复计算。

## 4. Knowledge Evidence 选择协议

### 4.1 仅显式选择，不做召回

前端传递 `knowledge_selections`：

```json
[
  {
    "note_version_id": 901,
    "evidence_ids": ["ev_abc", "ev_def"]
  }
]
```

服务端必须验证：

1. `note_version_id` 存在且属于已确认的 Knowledge Note Version；
2. 每个 `evidence_id` 通过 `knowledge_note_evidence` 关联到该 Note Version；
3. Evidence、Source、Snapshot 仍可读取，Evidence 原文和位置哈希与数据库一致；
4. 选择数量没有超过本设计上限，列表中无重复 ID。

客户端只提交用户点击过的 Evidence。服务端不能根据 Note 标题、JD、简历、关键词、Embedding、FTS 或模型输出追加任何 Evidence。没有选择 Knowledge 时，快照中的数组必须为空，而不是“自动使用当前 Knowledge”。

### 4.2 Knowledge 变化

Knowledge Note 新建版本不会修改旧 Evidence。旧 Proposal 的快照仍可读，但若原选 Evidence 不再属于当前 Note Version、Source 被归档/删除或其 hash 不一致，历史响应标记 `source_status=source_changed`，不改写 Proposal。

新生成必须重新选择当前可见的 Evidence；选中旧版本、不可见 Evidence 或不存在的 ID 返回 `422 interview_preparation_knowledge_selection_invalid`，不调用模型。历史 Proposal 的 Evidence 摘录从其冻结快照读取，不能回读新版本内容来覆盖旧审计链。

## 5. Proposal 数据模型与迁移

### 5.1 新表

新增 `interview_preparation_proposals`，使用当前仓库在 `0011_confirmed_interview_knowledge_capture` 之后的未占用迁移版本 `0012_interview_preparation_proposals`。实施前仍须由迁移测试确认该版本未被其他提交占用，禁止复用已存在版本。不修改既有表的字段或既有 API 语义。

| 字段 | 约束与用途 |
| --- | --- |
| `id` | 主键 |
| `application_id` | 非空；新生成时绑定 Application，历史读取按可见性检查 |
| `application_event_id` | 非空快照标识；不依赖事件删除后的实时行，保存原事件 ID 用于审计 |
| `resume_id` | 非空快照标识；Resume 物理删除后仍从快照历史查看 |
| `idempotency_key` | 非空；与 Application、Event 组成唯一键 |
| `generation_status` | `generating`、`provider_unknown`、`ready`；只有 `ready` 是用户可见 Proposal |
| `generation_revision` | 非负整数；用于 Provider lease/CAS |
| `provider_call_token` | 仅生成中存在的随机 token，不写日志 |
| `provider_lease_until` | 生成 lease 的失效时间；进程崩溃后允许同 key 安全接管 |
| `input_snapshot_json` | canonical JSON 冻结快照，包含 JD、Resume、所选 Evidence 和断言 |
| `source_fingerprint` | 输入快照 SHA-256 |
| `proposal_json` | 严格校验后的 Proposal 或固定安全空 Proposal；`ready` 时非空 |
| `proposal_hash` | `proposal_json` canonical JSON SHA-256；`ready` 时非空 |
| `failure_category` | 仅保存安全类别，如 `invalid_json`；不保存模型原文 |
| `created_at` / `completed_at` | 时间字段 |

唯一约束为 `(application_id, application_event_id, idempotency_key)`，并建立 Application、Event、Resume 和创建时间索引。事件和简历的快照身份不能用 `ON DELETE CASCADE` 抹掉；Proposal 自己保存输入快照和内部 ID。Application 物理删除是否级联清理历史由现有应用删除语义决定，Application 软删除不删除 Proposal。

`generating`/`provider_unknown` 是同一行中的持久化尝试状态，不是可见 Proposal。Proposal 一旦进入 `ready`，`input_snapshot_json`、`source_fingerprint`、`proposal_json`、`proposal_hash` 和创建时间均不可更新；后续重新生成必须使用新 key 创建新行。这样只用一张增量表也能在模型调用期间跨连接控制幂等 lease，而不会把半成品展示给用户。

### 5.2 迁移顺序

迁移启动时先运行现有 `Base.metadata.create_all()`，保证全新库可创建新模型；随后执行仅针对已存在旧结构的兼容性检查，再创建索引/唯一约束并记录 `0012_interview_preparation_proposals`。本任务不向既有表补列，因此不存在对不存在的旧表直接 `ALTER TABLE` 的路径。重复启动必须幂等，不能删除既有 Proposal、Knowledge 或 InterviewNote。

## 6. 快照、来源漂移与历史读取

### 6.1 新生成的两段式生命周期

1. 第一个短 session 使用 `BEGIN IMMEDIATE` 检查可见 Application、选定 interview event、Resume、JD 和 Knowledge selections，构建快照并计算指纹。
2. 先查询 `(application_id, event_id, idempotency_key)`。若已经是 `ready`，直接返回相同 Proposal，不能解析 Provider 配置、不能调用模型。若 `generating` 且 lease 未过期，返回“正在生成”状态，不发第二次 Provider 调用。若 `provider_unknown` 或 lease 已过期，CAS 接管新的 revision/token。
3. 事务提交并关闭 session 后才调用真实 AI；模型调用期间绝不持有 SQLite 连接。
4. Provider 返回后，以新短 session 执行 `BEGIN IMMEDIATE`，按 revision/token/status 做 CAS；陈旧回写必须丢弃，不写入模型原文。
5. 回写事务重新校验 Application 可见性、事件关系、Resume 当前 hash、JD 本次请求 hash 和已选 Knowledge Evidence hash。任何漂移返回 `409 interview_preparation_source_conflict`，不将结果写成 `ready`。
6. 没有漂移时，在同一事务内将校验后的 Proposal 或安全空 Proposal 写入该 attempt 并提交。并发请求只能看到同一个 `ready` 行。

### 6.2 历史读取与实时生成分离

历史列表/详情只读 `ready` Proposal，并要求 Application 当前可见。事件被删除、简历被删除或内容变化、Knowledge 来源变更时，历史 Proposal 仍从 `input_snapshot_json` 返回并标记来源变化；不会重新读取新的原文去覆盖快照。Application 软删除时历史接口返回 `404 interview_preparation_application_not_found`，前端清理当前卡片和待交接状态，不展示已隐藏投递内容。

历史状态算法固定为：

1. Application 不存在或不可见：`404`，不返回快照。
2. 当前 event 不存在、被删除、类型改变、转到其他 Application，或关键字段与事件快照不同：`event=source_changed`。
3. Resume 不存在、被软删除或当前内容 hash 与快照不同：`resume=source_changed`。
4. 任一选定 Evidence 不存在、不可见、脱离原 Note Version 或原文/hash 改变：`knowledge=source_changed`。
5. JD 没有既有 Application 单列；前端打开历史时提交当前已确认 JD 的 `current_jd_hash` 查询参数。参数存在且不等于快照中的 `jd_sha256` 时为 `jd=source_changed`；没有参数时为 `jd=not_checked`，不伪称当前。
6. 任一分项为 `source_changed`，整体 `source_status=source_changed`；没有变化且没有 `not_checked` 时为 `current`；否则为 `not_checked`。

`source_status` 只影响查看和重新生成提示，不改变不可变 Proposal。用户可以查看来源已变化的历史，但必须重新确认当前 Resume、JD、事件和 Evidence 并生成新 key 才能得到新 Proposal。

### 6.3 幂等键生命周期

- 首次点击确认时由持久的 AppShell/Pilot draft reducer 生成 `proposalAttemptKey`，按 `(applicationId, eventId)` 保存完整输入草稿和 key，不能只放在 Drawer 的局部 state。
- 成功返回 `201`，或同 key 命中 `200`，表示本次尝试结束；用户再次生成必须明确点击“重新生成”并创建新 key。
- `422` 前置校验、调用前 Application/Event/Resume/Knowledge 不可用等明确不写入错误，可以清除 key；不创建 Proposal。
- Provider 异常、超时、断网、网关错误、响应丢失、无稳定错误体和客户端取消请求都属于结果未知：保留 draft、key 和服务端 `provider_unknown/generating` 状态。关闭 Drawer、切换页面或重新挂载后必须用同 key 重试，不能新建 key。
- 慢调用期间切换投递或修改 JD/Resume/Knowledge 选择时，旧 draft 不能被新上下文复用；退出前将未知结果 draft 按旧 Application/Event 保留，当前页面使用新 draft。来源冲突 `409` 是确定未写入当前版本，提示重新确认并清除旧 key。
- 复用旧 Proposal 查看不会清除未决 key。历史列表不能按时间或摘要推断命中幂等结果，只有同一 `(application_id,event_id,key)` 才能恢复。

## 7. AI 输出契约与安全空结果

### 7.1 Provider 能力分支

若当前 Provider 配置明确为真实 JSON 布尔值 `supports_json_schema=true`，生成请求使用与下述契约等价的原生 JSON Schema；其他值（包括字符串 `"true"`、`"1"`、数字和 `null`）都按不支持处理，不能向 Provider 传递未知 `response_format` 参数。无原生 Schema 时使用严格 JSON 文本提示。

原生 Schema 只是输出约束能力，不能替代服务端的严格 JSON 解析、额外字段拒绝、有限数值检查、证据逐字校验、数组上限和来源漂移校验。

### 7.2 Proposal JSON

顶层只允许以下五个数组字段，禁止 `summary`、`score`、`recommendation`、`confidence`、`risk`、`reasoning`、`actions` 或任何额外字段：

```json
{
  "preparation_directions": [
    {"id": "direction_1", "text": "围绕岗位描述中明确出现的方向准备", "evidence_refs": []}
  ],
  "story_prompts": [],
  "review_points": [],
  "interviewer_questions": [],
  "items_to_clarify": []
}
```

每个数组项严格只允许 `id`、`text`、`evidence_refs` 三个字段；`id` 必须是唯一 ASCII 字符串（1–64 字符），`text` 为非空字符串（最多 1,000 个 Unicode 字符），`evidence_refs` 为 1–5 项的非空数组。五类数组各自最多 8 项。问题也必须引用证据；不能用问题形式隐藏无依据的岗位要求、面试官偏好或能力判断。

每个 Evidence ref 严格只允许：

```json
{
  "source": "jd|resume|knowledge_evidence",
  "path": "允许的冻结快照路径",
  "excerpt": "冻结快照中的逐字连续文本"
}
```

允许路径和摘录规则：

- `source=jd`：只能是 `/jd/text`，`excerpt` 必须逐字来自冻结 JD；
- `source=resume`：`path` 是选定 Resume `content_json` 的相对 JSON Pointer，不能使用其他 Resume 或上传文件路径；
- `source=knowledge_evidence`：`path` 只能引用本次快照分配的 canonical Evidence ID，`excerpt` 必须等于所选 Evidence 的冻结原文；
- `source=user_assertion`、`source=event`、`source=application`、`source=memory`、`source=old_proposal` 一律拒绝；
- Evidence ref 不得只写 ID 而省略 path/excerpt；空摘录、未知 ID、拼接摘录、改写摘录、引用未选 Evidence 或引用 JD/Resume 以外的字段均拒绝。

服务端在保存前把 canonical Evidence path 解析到快照，逐字检查 `excerpt`，不相信模型提供的 hash 或事实描述。任何具体建议没有合规 Evidence ref 都不能进入 `ready` Proposal。

### 7.3 安全空 Proposal

两次模型输出均未通过 JSON、结构、字段、数量或证据门禁时，服务端不返回 502，也不展示模型原文；服务端严格生成并校验固定安全空结构：

```json
{
  "preparation_directions": [],
  "story_prompts": [],
  "review_points": [],
  "interviewer_questions": [],
  "items_to_clarify": []
}
```

该结构唯一表达“目前没有可验证、可给出的面试准备建议”，不得附带总结、解释、失败原因、推断或模型文本。它以 `proposal_status=safe_empty` 作为正常 `201` Proposal 持久化，同一 key 后续始终返回同一安全空 Proposal。前端显示固定中文“暂无可验证的面试准备建议”，不显示任何模型 `summary`，也不把它当系统错误。

### 7.4 一次格式修复与失败诊断

首次输出失败后，服务端只允许一次修复请求。修复请求携带机器可读的一个失败类别：`invalid_json`、`unexpected_field`、`invalid_item_shape`、`limit_exceeded`、`missing_evidence_ref`、`unknown_evidence_ref` 或 `excerpt_mismatch`，要求只返回同一冻结快照下符合相同契约的 raw JSON。失败类别不得携带原始回复、快照、JD、简历、断言或证据摘录。

只对 JSON/结构/字段/数组上限/证据格式失败执行修复；Provider 鉴权、网络、超时、服务不可用和无法判断服务端是否写入的异常不重试，返回 `502 interview_preparation_provider_error` 并保留原 key。两次契约失败后按 7.3 写入安全空 Proposal。内部日志只记录 `failure_category`、是否执行过修复、修复次数、耗时和脱敏 Provider request id；不记录模型原文、输入快照、候选人内容、JD、断言、摘录或 API Key。

## 8. API 契约与错误映射

新增 Application-scoped API：

```text
GET  /api/applications/{application_id}/interview-preparation-proposals
GET  /api/applications/{application_id}/interview-preparation-proposals/{proposal_id}
POST /api/applications/{application_id}/interview-preparation-proposals
```

### 8.1 POST 请求

```json
{
  "event_id": 34,
  "resume_id": 56,
  "jd_text": "用户确认的岗位描述原文",
  "knowledge_selections": [],
  "user_assertions": [],
  "idempotency_key": "client-generated-key"
}
```

请求不接受 `job_url`、`jd_url`、`source_fingerprint`、`snapshot`、`proposal` 或模型输出字段。服务端自己读取事件、Resume 和 Knowledge Evidence；任何未知请求字段均返回 `422 interview_preparation_invalid_request`，不静默忽略可能扩大上下文的字段。

成功响应为：新建 `201`，同 key 的 ready 幂等命中 `200`，同 key 已有未过期 lease 的生成中状态 `202`。响应包含 `id`、`application_id`、事件/简历快照 ID、`source_fingerprint`、`source_status`、`proposal_status`、严格 `proposal`、`proposal_hash`、`created_at` 和分项来源状态。`202` 不含未完成 Proposal，不触发第二次 Provider 调用，客户端保留 key 并按同 key 查询/重试。

### 8.2 历史读取

历史接口只返回 `generation_status=ready`，不触发 AI、不触发写入。详情支持只读 `current_jd_hash` 查询参数；前端有当前 JD 时必须传入，服务端不把缺失参数伪装成 `current`。历史 Proposal 的 `input_snapshot_json` 只用于服务端来源检查与安全展示，Proposal 正文仍是保存时的严格结果。

历史查看可以复制 JD、简历片段、Knowledge Evidence 和建议文本，但复制不是写入。页面明确区分“冻结来源”和“当前来源已变化”，不能提供自动重新生成或接受动作之外的隐式操作。

### 8.3 稳定错误码

| 情况 | HTTP | 错误码 |
| --- | ---: | --- |
| Application 不存在、软删除或不可见 | 404 | `interview_preparation_application_not_found` |
| 缺少 event_id | 422 | `interview_preparation_event_required` |
| 事件不存在、非 interview、跨投递或不可用 | 422 | `interview_preparation_event_invalid` |
| 缺少 resume_id | 422 | `interview_preparation_resume_required` |
| Resume 不存在或不可见 | 404 | `interview_preparation_resume_not_found` |
| JD 缺失或为空 | 422 | `interview_preparation_jd_required` |
| 选择、数量、JSON 或输入大小非法 | 422 | `interview_preparation_invalid_request` / `interview_preparation_input_too_large` |
| 选定 Knowledge/Evidence 不属于当前已确认版本 | 422 | `interview_preparation_knowledge_selection_invalid` |
| 模型调用前后来源指纹或关系变化 | 409 | `interview_preparation_source_conflict` |
| 既有 Proposal 与同 key 的请求快照不同 | 409 | `interview_preparation_idempotency_conflict` |
| Provider/网络/超时/未知响应结果 | 502 | `interview_preparation_provider_error` |
| 历史 Proposal 不存在或不属于该 Application | 404 | `interview_preparation_proposal_not_found` |

所有错误响应保留稳定 `error_code`，但不把 Python 异常、Axios message、Provider 原文、JD、Resume、断言、Evidence 摘录或 API Key 放入公开响应。前端仅按 `error_code`/HTTP 状态映射固定中文；未知情况使用“面试准备建议暂时不可用，请稍后重试”。

## 9. 前端与 Pilot

### 9.1 结构化页面

面试事件入口打开原生 `InterviewPreparationProposalDrawer`；Pilot 只提供打开该 Drawer 的 Application-context 入口，不复制表单、不创建聊天消息、不伪造工具进度。Drawer 状态由 AppShell 或持久 reducer 按 `(applicationId,eventId)` 管理，至少保存：选择的 Resume、JD、Knowledge Evidence、断言、attempt key、请求状态和来源状态。抽屉卸载、详情切换或 Pilot 重挂载不能丢失未知结果的 key。

固定文案全部中文化：标题、说明、表单标签、占位提示、确认弹窗、加载、空状态、历史、来源变化、错误和无障碍标签均使用材料/面试准备专用文案字典。以下动态内容保持原文：JD、简历标题和正文、公司/职位、事件原文、Knowledge Evidence 摘录、AI 建议正文。英文固定短语扫描只断言已知 UI 短语不存在，不禁止动态英文数据。

### 9.2 证据展示与人工边界

五个区域固定显示：

- “准备方向”；
- “经历故事提示”；
- “建议复习的知识点”；
- “可以向面试官确认的问题”；
- “待确认事项”。

每个非空条目紧邻展示 Evidence 来源标签、原文路径和逐字摘录。来源标签统一为“岗位描述”“选定简历”“已确认 Knowledge Evidence”；路径和摘录保持原文。用户断言单独展示为“用户断言”，不进入建议证据标签。

安全空 Proposal 只显示固定的“暂无可验证的面试准备建议”，不显示模型原始 `summary`、失败类别或任何推断。来源变化的历史 Proposal 仍可展开和复制，但隐藏/禁用重新使用旧输入的直接操作；用户必须重新确认新输入后生成新 key。

### 9.3 加载、取消与未知结果

- 确认前取消：不发送请求，不创建服务端行，清除本地草稿。
- 请求进行中关闭、超时、断网或响应丢失：显示“结果待确认”，保留 AppShell draft 和原 key；关闭不触发删除或新建 key。
- 重新进入同一 Application/Event：优先用原 key 查询已有 ready 结果，否则用同 key 重试。
- 稳定 `422/404` 前置失败：显示固定中文并清理不可继续的 key；稳定 `409` 来源冲突：提示重新选择/确认并清理旧 key。
- `502` Provider/网络错误：显示“AI 服务暂不可用，结果待确认，请使用原尝试重试”，保留 key，不自动重试。
- 生成成功或安全空结果后，用户点击“重新生成”才创建新 key；没有自动接受、自动保存或下游 handoff。

## 10. 测试与验收

### 10.1 后端数据与资格

- 当前可见 Application + `event_type=interview` 成功；非 interview、跨投递、已删除/不可见事件、缺少 event、缺少 resume、不可见 resume 和空 JD 分别命中固定 `422/404`，且 Provider 调用次数为零；
- `job_url`/`jd_url`/任意外部 URL 抓取路径不被调用；输入只接受用户确认的文本；
- Knowledge 只接受显式选中的当前已确认 Note/Evidence；零选择不触发自动召回；伪造 note version、evidence ID、跨版本 Evidence、归档/删除 Evidence 和超限选择均拒绝；
- 用户断言数量、长度、JD/Resume/Knowledge 大小和 idempotency key 边界测试；CJK、emoji、换行和原文 hash 保持确定性。

### 10.2 快照、漂移和幂等

- 输入快照只含事件最小上下文、JD、选定 Resume、明确选定 Evidence 和独立断言；不含旧 AI Proposal、完整旧复盘、Memory、未选 Knowledge、location、job_url 或外部内容；
- Resume 内容、事件字段、JD hash、Knowledge Evidence 原文/归属在模型调用期间变化，最终短事务返回 `409 interview_preparation_source_conflict`，不产生 ready Proposal；
- 事件删除后历史 Proposal 仍可读并标记 `event=source_changed`；新生成返回 `422 interview_preparation_event_invalid`；Application 软删除后历史/生成返回安全 `404`，前端清理卡片；Resume/JD/Knowledge 变化只标记历史来源变化，不改写历史；
- 同一 key 在 Provider 配置不可用时先返回已有 ready Proposal，不因当前 Provider 配置失败而覆盖幂等结果；不同快照复用同 key 返回 `409 interview_preparation_idempotency_conflict`；
- 两个独立 SQLite session 并发同 key，使用可控 Provider barrier，断言最多一个有效 Provider lease、最多一条 ready Proposal、第二请求不抢占未过期 lease，陈旧 revision/token 回写失败；
- Provider 超时、断网、普通 5xx、响应丢失和客户端取消保留 key；重新挂载后同 key 恢复。成功/安全空结果后新生成必须使用新 key。

### 10.3 严格 AI 契约

- 原生 JSON Schema 能力为真实布尔 `true` 时才发送 `response_format`；字符串、数字、`null` 和未配置均走严格 JSON 文本；
- 合法五数组结构成功；fenced JSON、NaN/Infinity、重复键、顶层额外字段、条目额外字段、错误类型、重复 ID、超限数组、空/未知/伪造来源、错误路径和非逐字 excerpt 均被识别为安全失败；
- 首次契约失败携带机器类别并恰好修复一次；Provider 异常只调用一次；两次契约失败落库固定安全空 Proposal `201`，不泄露模型原文；
- 建议逐项引用 JD/Resume/已确认 Knowledge Evidence；`user_assertion`、event、Application、Memory 和旧 Proposal 不能成为 Evidence ref；
- 安全空 Proposal 的五个数组严格为空，返回后同 key 始终复用同一 hash，不创建任何下游领域对象。

### 10.4 前端与无跨领域写入

- 投递详情面试事件入口和 Pilot 入口只打开同一个受控 Drawer；重新挂载、切换投递、未知结果重试都复用原 key；
- 选择简历、粘贴 JD、选择 Knowledge、填写断言、确认弹窗、取消路径和输入限制均有测试；
- 历史列表/详情可读，来源变化、事件删除、Resume/JD/Knowledge 漂移、404/409/422/502 和未知错误均显示安全中文；
- 安全空状态不展示为系统错误，不显示原始模型内容；每条非空建议显示中文来源标签、原文路径和摘录；
- 测试数据库中 Application、Event、Resume、Material Kit、Question、Knowledge、Memory、Reminder 和状态记录在生成前后数量及内容不变；
- 网络断言只允许本地 `/api`、静态资源和已配置 AI Provider，不允许招聘平台或任意 URL 请求。

### 10.5 隔离 real-AI 浏览器闭环

使用一个连续、隔离的验收 harness：复制现有 `config.json` 到临时 `OFFERPILOT_DATA`，使用确认空闲且启动后验证归属于 harness 进程树的临时端口，启动服务后只在该目录创建合成 Application、一个 interview 事件、至少一份 Resume、一个非空 JD 和至少两条已确认 Knowledge Evidence。禁止使用用户实际数据库。

浏览器从 `$baseUrl` 进入投递详情，定位合成投递和面试事件，进入“面试准备建议”：

1. 选择简历、确认 JD、选择 Knowledge Evidence，确认发送给 AI；
2. 真实 Provider 生成 Proposal；允许安全空结果，但三组非空合成输入请求都不得出现未处理异常；至少一组必须得到逐项有效 Evidence 的非空建议，其余可为安全空 Proposal；
3. 页面检查准备方向、经历故事提示、复习点、面试官问题和待确认事项的证据展示，固定文案中文，动态原文不被翻译；
4. 关闭并重新打开 Drawer，模拟一次响应丢失/结果未知，确认同 key 重试而不是新建 Proposal；查看历史快照；
5. 修改 Resume/JD/Knowledge 或删除面试事件，确认旧 Proposal 仍可读并标记来源变化，新生成被阻止或返回稳定 `409/422`；
6. 断言没有 Application/Event/Resume/Material Kit/Question/Knowledge/Memory/Reminder/状态写入，没有自动投递，网络没有招聘平台请求；
7. 停止且只停止 harness 启动的进程树，清理临时 Application、Event、Resume、Proposal 和相关数据，最后断言临时目录无残留；不得输出 API Key、完整 JD、完整简历、Knowledge 全文或模型原文。

若 Provider 三组均返回安全空 Proposal，记录为“真实模型未产生可验证改写但安全降级正确”；这不等价于非空建议验收通过，必须再次提高提示稳定性后复验。

## 11. 兼容性、风险与后续计划

破坏性变化：无。新增表、模型、API 和前端入口不改变既有 Application/Event/Resume/Knowledge/Material Kit/InterviewNote API；旧数据库通过增量迁移保持可启动，旧数据无需回填。

主要风险与控制：

- 模型把岗位描述改写成候选人事实：Evidence source/path 白名单与逐字 excerpt 校验拒绝；
- 模型猜测面试官问题或通过率：输出契约没有分数/预测字段，问题也必须有证据；
- 未选 Knowledge 或旧 AI 建议被隐式带入：服务端只从请求中显式选择的 Evidence 构建快照，且不读取 Note 派生成文案；
- 慢 Provider 占用 SQLite 或产生重复记录：短 session、lease、`BEGIN IMMEDIATE`、revision/token CAS 与同 key 唯一约束共同控制；
- 未知结果重试重复生成：AppShell 持久 draft 和服务端幂等行先查后生成；
- 真实验收污染本地数据或误访问招聘平台：临时数据目录、受控进程树、端口归属验证、scoped cleanup 和网络 allowlist；
- 后续要创建题目、练习、Knowledge 或 Memory：必须另写设计和 API 契约，本功能不提供任何跨领域写入。

本设计获批后，下一步另行编写测试先行实施计划；计划获批前不修改模型、迁移、API、AI、前端或 smoke 实现代码。
