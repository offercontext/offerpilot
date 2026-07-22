# 证据门控的面试复盘建议设计

日期：2026-07-22
状态：待复审；本阶段只提交设计，不进入代码实现
范围：将用户保存的 InterviewNote 绑定到具体面试事件，并基于该复盘及事件元数据生成可审阅、可追溯的 AI 建议。

## 1. 目标与非目标

### 1.1 目标

1. 允许用户将一条 `InterviewNote` 绑定到同一 Application 下的一条 `event_type=interview` 的 `ApplicationEvent`。
2. 为已保存复盘生成不可变的 `InterviewReviewProposal` 快照。每个建议都能追溯到本次复盘的冻结字段，不把模型推测伪装成事实。
3. 复盘编辑后保留旧建议作为历史快照并标记来源已变化；用户明确重新生成时才产生新的建议。
4. 保留人工确认：生成建议、查看建议、打开预填动作均不自动写入事件、题库、知识库、Memory、Application 状态或其他外部平台。

### 1.2 非目标

- 不重做 InterviewNote 基础 CRUD、行动队列或提醒派生逻辑。
- 不读取 JD、其他 Resume、聊天历史、长期 Memory 或招聘网站，不增加 AI 工具调用。
- 不做自动外联、自动投递、自动状态迁移、模拟面试、录音或转写。
- 不将“表现”“弱点”“能力不足”等判断写入长期 Memory；建议只能作为本次复盘的可审阅草稿。

## 2. 领域边界与数据来源

本功能的唯一 AI 输入是用户本次复盘的冻结字段，以及绑定面试事件的有限元数据：

```text
InterviewNote snapshot
  company
  position
  round
  date
  questions
  self_reflection
  difficulty_points
  mood

InterviewEvent snapshot
  id
  application_id
  event_type=interview
  subtype
  round
  scheduled_at
  duration_minutes
  location
  status
```

Application 只用于可见性和同投递关系校验；公司名、职位名和事件元数据不作为“候选人表现”的证据。AI prompt、日志和错误响应不得包含 JD、Resume、聊天、Memory 或完整数据库对象。

## 3. 面试事件绑定

### 3.1 数据模型

为 `interview_notes` 增加可空字段：

```text
application_event_id INTEGER NULL
  REFERENCES application_events(id) ON DELETE SET NULL
```

增加普通索引 `idx_notes_event`，并增加 SQLite 部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_interview_notes_event_main
ON interview_notes(application_event_id)
WHERE application_event_id IS NOT NULL;
```

这表示一个面试事件最多有一条主复盘；复盘本身仍可不绑定事件。

### 3.2 绑定校验

创建或更新复盘时，如果 `application_event_id` 非空，服务端在同一短事务中校验：

1. 事件存在且可见；
2. 事件的 `event_type` 精确为 `interview`；
3. 事件所属 Application 可见且与复盘的 `application_id` 相同；
4. 复盘已属于一个 Application。独立复盘不能直接绑定投递事件；
5. 该事件没有另一条主复盘。

关系不合法返回稳定的 `422`；事件已经被另一条复盘占用返回稳定的 `409`。唯一索引是最终并发防线，冲突转换为同一 `409`，不得静默改绑或覆盖其他复盘。

`application_id` 或 `application_event_id` 的改变也必须重新执行全部关系校验。更新失败不改变原绑定。

### 3.3 删除语义

- 删除面试事件时，数据库外键将 `InterviewNote.application_event_id` 置空；不删除用户复盘，也不删除已有建议快照。
- Application 软删除不删除复盘、事件或建议快照；涉及该投递的读写接口按不可见资源返回 `404`，防止继续生成或交接。
- 复盘物理删除时，属于该复盘的建议快照一并删除；复盘编辑不删除、不覆盖任何历史建议。

## 4. 不可变建议快照

### 4.1 新表

新增 `interview_review_proposals`：

| 字段 | 约束与用途 |
| --- | --- |
| `id` | 主键 |
| `note_id` | 非空外键到 `interview_notes`；复盘删除时级联删除建议 |
| `application_event_id` | 生成时绑定事件 ID 的快照，可空，仅用于审计展示 |
| `idempotency_key` | 非空；与 `note_id` 组成唯一键 |
| `input_snapshot_json` | 严格 JSON，保存本次 note/event 输入快照 |
| `source_fingerprint` | 输入快照的 canonical JSON SHA-256 |
| `proposal_json` | 严格校验后的建议 JSON，不保存原始模型回复 |
| `proposal_hash` | `proposal_json` canonical JSON SHA-256 |
| `created_at` | 生成并落库时间 |

增加 `idx_interview_review_proposals_note`，并增加唯一约束 `(note_id, idempotency_key)`。建议快照只增不改；模型名称、token、原始错误和原始输出不进入本表。

### 4.2 指纹与来源状态

服务端对固定字段按稳定键顺序、UTF-8、无额外空白进行 canonical JSON 序列化后计算 `source_fingerprint`。指纹输入包含第 2 节列出的 note/event 字段，不包含数据库时间戳、模型字段或当前 UI 状态。

读取历史建议时，以当前可见 note/event 重新计算指纹：

- 相等：`source_status=current`；
- 不相等，或绑定事件已删除/不可见：`source_status=source_changed`。

历史 `input_snapshot_json` 和 `proposal_json` 仍可只读展示；`source_changed` 时禁止把该建议当作当前复盘的可执行依据。前端应明确显示“来源已变化，请重新生成”，不得静默重算或覆盖旧快照。

### 4.3 幂等与并发生命周期

用户首次确认生成前由前端生成 `proposalAttemptKey`。成功、确定失败或用户修改复盘前复用同一 key；超时、断网、响应丢失属于结果未知，必须保留 key，优先使用同一 key 重试或查看明确的历史结果。

`POST` 生成接口的幂等规则：

1. 先以 `(note_id, idempotency_key)` 查询已有建议；存在时只返回该建议，不调用 AI、不创建第二条记录。返回中的 `source_status` 按当前快照重新计算。
2. 不存在时先在短 session 冻结 note/event snapshot 并关闭 session，再调用 AI。AI 调用期间不持有 SQLite 连接。
3. AI 返回并通过严格校验后，使用新的短 session 执行 `BEGIN IMMEDIATE`，重新读取可见 note/event，重新计算指纹；指纹或绑定关系变化则返回 `409`，不插入建议。
4. 指纹仍一致时，在同一事务内检查唯一幂等键、插入建议并提交。并发请求若先插入，后到请求读取并返回已存在结果。
5. Provider 错误、超时或不可验证输出不写入建议；客户端不得因未知结果自动生成新 key。

## 5. AI 输入与严格输出契约

### 5.1 Prompt 边界

系统 prompt 必须明确：

- 只能使用本次冻结 InterviewNote 和 InterviewEvent 元数据；
- 不得声称“面试官评价”、外部事实、候选人能力结论或未记录的题目答案；
- 没有复盘依据时，只能放入待澄清问题；
- 只返回 raw JSON，不得返回 Markdown、代码围栏、解释文字或额外字段；
- 所有用户可见主张必须通过本次复盘字段证据引用验证。

### 5.2 JSON 结构

顶层只允许以下字段：

```json
{
  "summary": {
    "text": "string",
    "evidence_refs": [
      {"source": "interview_note", "path": "/self_reflection", "excerpt": "string"}
    ]
  },
  "observations": [
    {
      "id": "string",
      "text": "string",
      "evidence_refs": [
        {"source": "interview_note", "path": "/questions", "excerpt": "string"}
      ]
    }
  ],
  "clarifications": [
    {"id": "string", "question": "string"}
  ],
  "practice_focuses": [
    {
      "id": "string",
      "text": "string",
      "evidence_refs": [
        {"source": "interview_note", "path": "/difficulty_points", "excerpt": "string"}
      ]
    }
  ],
  "next_questions": [
    {"id": "string", "question": "string"}
  ]
}
```

校验规则：

- 顶层和每个对象拒绝额外字段；所有 ID、文本、路径和摘录均为字符串；数组长度受后端合理上限约束，避免模型输出失控；
- `summary`、每个 `observation`、每个 `practice_focus` 的 `evidence_refs` 必须非空，除非 `summary.text` 是服务端允许的固定无依据安全文案；
- `source` 只能是 `interview_note`；`path` 只能是 `/questions`、`/self_reflection`、`/difficulty_points`、`/mood`；
- `excerpt` 必须非空，并且是冻结快照对应字段的逐字连续片段，不能由模型改写、拼接或引用事件/JD/Resume；
- `clarifications` 和 `next_questions` 只能表达问题，不得在问题字段中夹带未经证据支持的结论；
- `summary` 是用户可见模型主张，也必须带证据；若四个证据字段均为空，只能返回固定安全摘要、空的观察和练习重点，并将需要用户补充的内容放入问题数组；
- `json.loads` 使用拒绝 `NaN`、`Infinity`、`-Infinity` 的解析器；拒绝 fenced JSON、重复键、非法 UTF-8、非 JSON 顶层值和任何额外字段；
- 校验失败统一归类为 `interview_review_unverifiable`，返回 `502`，不保存建议，不向前端或日志写入原始模型回复。

Provider 鉴权、网络、超时和服务不可用统一归类为 `interview_review_provider_error`，返回 `502`，同样不保存建议。错误日志只记录安全失败类别和 note/application 的内部关联标识，不记录复盘正文、事件完整内容、API Key 或模型原文。

## 6. API 契约

### 6.1 复盘绑定

沿用现有 InterviewNote 路由，仅增量扩展字段，不改变旧请求的合法语义：

```text
GET  /api/applications/{application_id}/notes
POST /api/applications/{application_id}/notes
GET  /api/notes/{note_id}
PUT  /api/notes/{note_id}
```

响应的 `InterviewNote` 增加 nullable `application_event_id`。创建/更新 payload 可带同名字段；省略时保留现有“未绑定”行为。跨投递、非 interview 事件、不可见事件和重复主复盘按第 3.2 节返回 `404`、`422` 或 `409`，错误文本不作为前端契约。

### 6.2 建议生成与历史

新增只读/生成接口：

```text
GET  /api/notes/{note_id}/interview-review-proposals
GET  /api/notes/{note_id}/interview-review-proposals/{proposal_id}
POST /api/notes/{note_id}/interview-review-proposals
```

生成请求体仅包含：

```json
{"idempotency_key": "client-generated-key"}
```

服务端从 note/event 当前记录构建输入快照，不接受客户端上传的复盘正文、事件元数据、指纹或 proposal JSON。成功返回 `201`（新建）或 `200`（同 key 幂等返回），响应包含 `id`、`note_id`、`application_event_id`、`source_fingerprint`、`source_status`、`proposal`、`proposal_hash`、`created_at`。

稳定错误语义：

| 情况 | HTTP | 错误码 |
| --- | --- | --- |
| note/application/event 不存在或不可见 | 404 | `interview_review_not_found` |
| 复盘没有可用的 interview 事件 | 422 | `interview_review_event_required` |
| 生成前后指纹或绑定关系变化 | 409 | `interview_review_source_conflict` |
| Provider 不可用 | 502 | `interview_review_provider_error` |
| 输出严格校验失败 | 502 | `interview_review_unverifiable` |

前端仅按错误码/HTTP 状态显示固定中文文案，禁止透传 `response.data.error`、Axios message、Python exception 或模型文本。

## 7. 前端交互

### 7.1 入口与状态

- 面试事件卡片显示“记录复盘”；已有绑定复盘显示“查看复盘”。事件列表只展示当前可见 Application 的 `event_type=interview`。
- 复盘表单保留现有字段和 CRUD；绑定事件是显式选择，保存前展示绑定的公司、职位、轮次和时间。
- 已保存且有绑定事件的复盘显示“生成复盘建议”。首次生成前必须弹出确认，明确提示“本次复盘内容与面试事件信息将发送给当前配置的 AI 服务”。
- 生成中禁用重复提交；结果未知时保留同一个 `proposalAttemptKey`，显示“结果待确认/使用原尝试重试”，不自动重试。
- 建议历史按生成时间列出；编辑复盘后旧卡片显示“来源已变化”，仍可查看快照但不能被当作当前建议直接执行。点击“重新生成”产生新的 key。

### 7.2 建议卡片

结构化展示并固定区分：

- “用户记录”：复盘字段及其原文；
- “AI 建议”：摘要、已观察到的表现、练习重点；每项显示证据来源标签和原文摘录；
- “待澄清问题”：模型无法从本次记录确认的内容；
- “下次可追问”：只作为问题清单，不表示已发生事实；
- “来源状态”：当前来源或来源已变化。

证据标签固定为“复盘问题”“自我反思”“困难点”“情绪记录”；路径和摘录保留原文。不得显示“面试官评价”“平台已验证”或自动判断类措辞。

### 7.3 预填动作与 HITL

“创建跟进”“开始练习”“保存为知识草稿”只打开对应的预填表单：

- 创建跟进：仅预填用户可编辑的行动表单，不写入事件或提醒；
- 开始练习：仅打开题库练习表单，不创建题目、不写入题库；
- 保存为知识草稿：仅打开知识草稿编辑器，不写 Knowledge、Memory 或 Source。

用户确认这些后续表单时仍沿用各自现有人工确认流程。本功能不提供直接写入回调。

### 7.4 Pilot 入口

Pilot 只增加 Application 上下文的“打开面试复盘”入口，导航到原生复盘页面/抽屉并传递 `applicationId`，不复制复盘表单、不新增开放式工具、不伪造聊天消息或工具进度。复盘生成、历史查看和所有写入仍由原生复盘流程承载。

## 8. 增量迁移与兼容性

使用现有 `schema_migrations` 机制新增一个版本：

1. `ALTER TABLE interview_notes ADD COLUMN application_event_id INTEGER NULL`；
2. 创建 `idx_notes_event`；
3. 创建 `interview_review_proposals` 表、索引和 `(note_id, idempotency_key)` 唯一约束；
4. 创建 `uq_interview_notes_event_main` 部分唯一索引；
5. 既有 InterviewNote 的新字段全部为 `NULL`，既有 CRUD、行动队列和提醒数据无需回填或重算。

启动时 migration 必须幂等；旧数据库升级失败时不得删除既有表或数据。现有未绑定复盘继续可读、可编辑；只有绑定事件后才可生成本功能建议。

## 9. 测试与验收

### 9.1 后端

- migration：空库、已有库、重复启动和既有未绑定复盘兼容；
- 绑定：同投递 interview 事件成功，非 interview、跨投递、不可见事件、重复主复盘分别返回预期错误；解绑不删除复盘；删除事件后绑定字段变空；Application 软删除后相关读取/生成返回 404；
- 指纹：首次生成保存快照；复盘编辑后旧建议仍存在且标记 `source_changed`；事件元数据变化同样标记来源变化；
- 幂等：同 note/key 只返回同一记录，模型只调用一次；并发插入不产生重复建议；网络未知重试使用原 key；
- 漂移：模型调用期间改变复盘或绑定事件，第二短事务返回 `409` 且数据库没有错误版本；
- AI 校验：合法输出成功；fenced JSON、额外字段、重复键、NaN/Infinity、伪造路径、伪造摘录、空 evidence_refs、将事件/JD/Resume 当证据均安全失败；
- Provider：网络、鉴权、超时和无配置均返回带稳定错误码的 `502`，不落库、不泄露原始输出；
- 写入边界：生成建议及预填动作不改变 Application 状态、不创建事件/提醒/题库/知识/Memory。

### 9.2 前端

- 事件与复盘入口、绑定确认、重复绑定错误和删除事件后的解绑展示；
- 生成确认弹窗、加载、同 key 重试、历史快照和来源已变化状态；
- 结构化建议、证据标签/路径/摘录、用户记录与 AI 建议区分；
- 预填动作只打开表单，不直接调用写入 API；
- `404/409/422/502` 和未知错误只显示固定中文，不显示 Axios/服务端原文；
- 软删除后清理当前卡片，不能继续生成或触发后续动作；
- 固定英文短语扫描仅检查已知固定 UI 文案，不禁止英文用户数据、事件原文或 AI 摘录。

### 9.3 隔离真实 AI 浏览器闭环

在临时数据目录中复制现有 AI 配置，不使用用户真实数据库：

1. 创建合成 Application、一个 `event_type=interview` 的面试事件和绑定 Resume 不相关的最小复盘；
2. 浏览器打开复盘入口，保存复盘并确认发送给当前 AI；
3. 真实生成建议，检查摘要/观察/练习逐项显示复盘证据，空证据时只出现澄清问题；
4. 打开“创建跟进”“开始练习”“保存为知识草稿”的预填表单后取消，断言没有新增事件、提醒、题库、知识、Memory 或 Application 状态变化；
5. 编辑复盘，确认旧建议仍显示来源已变化；重新生成才创建新建议；
6. 删除事件或软删除 Application，确认页面显示安全中文 404、禁止继续生成和动作；
7. 断言网络请求仅到本地 `/api` 与已配置 AI Provider，无招聘平台访问；
8. 停止隔离服务、删除合成 Application/事件/复盘/建议并断言临时目录无残留；不输出 API Key、完整复盘、完整事件或模型原文。

## 10. 破坏性变化与风险

破坏性变化：无。字段增量可空、旧数据无需迁移内容，既有 InterviewNote CRUD 和行动/提醒派生逻辑保持兼容。

主要风险及控制：

- 模型把复盘内容扩写为能力判断：严格 evidence_refs 和字段逐字校验拒绝；
- 复盘或事件在慢模型调用期间改变：第二短事务 `BEGIN IMMEDIATE` 重查指纹并返回 `409`；
- 旧建议被误当作当前建议：响应提供 `source_status`，前端显式标记并阻止后续建议动作；
- AI 或浏览器验收污染本地数据：real-AI 使用隔离目录、受控进程和 scoped cleanup；
- 用户把预填动作误解为已保存：按钮和确认文案明确“仅打开预填表单”，不触发领域写入。

本设计通过复审后，下一步另行编写测试先行实施计划；在计划获批前不修改模型、迁移、API、前端或 smoke 代码。
