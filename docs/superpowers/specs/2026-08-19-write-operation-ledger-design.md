# Write Operation Ledger 设计

状态：待复审

日期：2026-08-19

分支：`feat/20260819-write-operation-ledger`

固定基线：`5e560580e86da7d1eb272e0df9d3d13304717499`（Tool Execution Pipeline 第二期最终提交）

## 1. 背景

前两期已经建立了两条互补但边界不同的基础设施：

- Durable Execution Journal 记录 Run / Segment / Event，故障时 fail-open，只用于诊断；
- Tool Execution Pipeline 统一了 25 个模型可见工具的契约、校验、确认、类型化结果和执行顺序，但只保证单次 `execute_prepared()` 内最多调用一次 executor。

当前 12 个模型可见写工具和 3 个确定性 Legacy 写动作最终都写入同一个业务 SQLite，但 Repository 各自创建 Session 并自行提交。确认 claim、领域写入、工具结果、Pending Action 清理分属多个事务。因此进程可能在以下位置退出：

```text
确认 claim 已提交
→ 领域写入已提交
→ ToolMessage / Pending Action 尚未持久化
→ HTTP 或 SSE 响应丢失
```

此时客户端无法安全判断第一次写入是否成功。重试可能再次调用 executor，现有 15 分钟 confirmation claim lease 只能减少并发，不能给出跨请求的业务 exactly-once。

第三期引入 Write Operation Ledger。Ledger 是业务写操作的幂等与结果真值，但不是领域状态真值，也不是事件溯源：

```text
Domain tables
  → 当前业务状态的真值

Write Operation Ledger
  → 某个 operation_id 是否提交、首次结果是什么的真值

Durable Journal
  → 执行过程发生过什么的诊断记录
```

## 2. 目标

本期必须实现：

1. 每个 Agent 发起的真实业务写入获得服务端生成、持久化的 `operation_id`。
2. 相同 `operation_id` 的领域事务最多提交一次。
3. 响应、进程或 SSE 连接在领域提交后丢失时，重试回读首次结果，不再次调用 executor 或 Provider。
4. Ledger 与领域写入共享一个 SQLite 事务；不存在“领域成功、Ledger 未提交”或相反状态。
5. 生命周期可审计：

   ```text
   proposed
     → rejected
     → approved → claimed → committed | failed
   ```

6. 明确区分领域写入结果和后续说明交付结果，能够表示“领域已 committed，但 Provider 说明或传输失败”。
7. 保留现有 HITL、Pending Action、确认编辑、确认拒绝、CAS、业务归属校验、Provider Schema、用户可见工具结果和调用顺序。
8. 12 个 Typed 写工具、3 个确定性 Legacy 写动作以及现有 4 类 AI 写入补偿操作全部纳入机械清单；不能静默漏接。
9. Ledger 故障时写操作 fail-closed，executor 为零次；读工具和非 Agent 业务界面不因 Ledger 不可用而停止。
10. 不把原始参数、异常对象、Prompt 或模型回答写入 Ledger、Journal 或普通日志。

## 3. 非目标

本期不实现：

- Context Projector；
- SSE reconnect/replay 事件流；
- 多 Agent、后台 Wakeup 或分布式数据库；
- 任意外部 HTTP、Provider、文件系统或浏览器副作用的 exactly-once；
- 对不同 `operation_id` 做语义去重；
- 从 Ledger 重建领域数据库；
- 把所有手工 UI / REST CRUD 写入改造成 Agent Operation；
- 把 3 个确定性 Legacy 动作迁移为模型可见 Typed Tool；
- 新的用户可见 Operation 调试界面；
- Ledger key rotation、归档或清理策略；
- 取代领域 Repository 已有的 revision、归属、唯一约束和 idempotency key。

## 4. 精确范围

### 4.1 12 个 Typed 主写操作

```text
create_application
update_application_status
create_application_event
update_application_event
delete_application_event
add_note
update_note
delete_note
update_offer
save_offer_assessment
resume_update_career_intent
resume_rewrite_highlight
```

### 4.2 3 个确定性 Legacy 写操作

```text
save_application_jd_version
create_application_submission_snapshot
record_application_outcome
```

它们继续由服务端确定性流程创建、由可信 Pending Action 恢复，仍不进入 Provider Tool Schema。本期只让其领域提交经过 Ledger，不借机迁移 Legacy Tool 协议。

### 4.3 4 类现有补偿写操作

```text
undo:update_application_status
undo:create_application
undo:create_application_event
undo:add_note
```

补偿操作作为 `operation_role=compensation` 的子 Operation，引用原始 `parent_operation_id`。同一原始 Operation 只允许一个成功补偿 Operation。重试已经成功的补偿时回读首次补偿结果，不把第二次 CAS 冲突误报给用户。

### 4.4 明确排除

Conversation / ChatMessage / Pending Action 的控制状态持久化不是“领域业务写入”，不单独建立 Operation。它们仍参与 proposal、claim 和 delivery 的 CAS。手工表单、普通 REST CRUD、Knowledge、Interview、Offer Negotiation 等非 Agent Tool 写入维持各自既有幂等契约。

“本期全部写入”特指上述 Agent Runtime 15 个主写入口和 4 个既有补偿入口，不表示 OfferPilot 所有 API 写端点。

## 5. 方案比较

### 方案 A：Ledger 与领域写入分别提交

先把 Ledger 标记 claimed，再调用现有 Repository；结束后把 Ledger 标记 committed。

优点是改动小。缺点是任意两个提交之间退出都会产生无法自动判定的分叉：claimed 可能没有领域写入，领域写入也可能已经成功但 Ledger 仍是 claimed。增加 lease 只能把未知状态延后，不能证明结果。

不采用。

### 方案 B：给每个领域表增加 `operation_id`

在 Application、Event、Note、Offer、Resume 等表分别增加唯一列，以领域行本身承担幂等。

它能保护部分 create，但 update/delete、一个操作更新多行、失败结果回读和统一审计仍需要另一套协议。它还把 Harness 身份污染到所有领域模型中。

不采用。

### 方案 C：同库 Unit of Work + 统一 Ledger（采用）

Coordinator 打开一个业务 Session 和 `BEGIN IMMEDIATE` 事务，原子完成 Pending claim、Ledger claim、领域 executor、结果投影与 Ledger terminal。Repository 在此路径使用显式绑定的外部 Session，只 `flush`，绝不自行 commit/rollback。

```text
prepare / mutable recheck
  → BEGIN IMMEDIATE
  → Pending claim CAS
  → Ledger identity / terminal replay check
  → approved transition
  → claimed transition
  → tool.started
  → SAVEPOINT
  → transactional executor
  → result + undo + transport projection
  → committed | failed transition
  → COMMIT
```

优势：只有一个原子提交点；进程退出会同时回滚领域变更和本次 Ledger transitions；提交后任何重试都能读到稳定 terminal。代价是需要逐领域拆出无自提交的 Session-bound 核心方法。本期 15 个 executor 均为本地 SQLite 操作，不包含网络或 Provider 调用，适合该方案。

## 6. 核心保证与限制

### 6.1 保证

对服务端生成且身份匹配的同一 `operation_id`：

- 最多存在一个 committed 领域事务；
- committed/failed/rejected 终态不可变；
- committed 重试返回首次 `result_json`、可见工具结果、transport projection 和 undo；
- failed 重试返回首次固定失败分类和可见错误；
- rejected 重试保持 rejected，executor 永远为零次；
- 不会因为 Journal、renderer、transport 或后续 Provider 失败而再次调用 executor；
- 不会在 commit 状态未知时自动进行第二次 executor 调用。

### 6.2 不保证

- 不同 `operation_id` 即使参数完全相同，也表示两个独立、经用户分别确认的操作；Ledger 不自动合并。
- executor 在一个已确定整体回滚的本地事务中可能被后续请求再次调用；保证的是领域提交最多一次，不是进程内 Python 函数调用在所有崩溃模型下恰好一次。
- 本协议只允许事务内本地 SQLite 副作用。未来带外部网络、文件或 Provider 副作用的写工具必须另行设计 outbox/remote idempotency，不得直接声明为本期 transactional executor。

## 7. 数据模型

迁移版本固定为 `0026_write_operation_ledger`，新增两张表，并为 Conversation 增加两个私有列。

### 7.1 `write_operations`

| 字段 | 约束与语义 |
| --- | --- |
| `id` | 36 位小写 UUID，主键，即 `operation_id` |
| `operation_role` | `primary` / `compensation` |
| `parent_operation_id` | 补偿操作引用原始 Operation；primary 必须为空 |
| `conversation_id` | nullable FK，`ON DELETE SET NULL`；Conversation 删除后 Ledger 保留 |
| `agent_run_id` | nullable 36 位 UUID；Journal 不可用时允许为空；刻意不对 fail-open Journal 建 FK |
| `tool_call_id` | primary 必填的受控 Provider/server call id；补偿可为空 |
| `tool_name` | 精确 Operation manifest 中的名称 |
| `adapter_kind` | `typed` / `legacy_deterministic` / `compensation` |
| `status` | `proposed` / `rejected` / `committed` / `failed` |
| `fingerprint_key_id` | Ledger HMAC key id |
| `proposal_fingerprint` | 原始 proposal 参数的 HMAC-SHA256 |
| `input_fingerprint` | 批准后 effective arguments 的 HMAC-SHA256；未批准时为空 |
| `confirmation_fingerprint` | confirmation token 的 HMAC-SHA256；不保存 token 原文 |
| `result_contract` | terminal 结果 codec：`typed_json_v1` / `legacy_string_v1` / `compensation_json_v1` / `rejection_json_v1` |
| `result_json` | terminal 的 canonical typed/legacy/rejection result envelope |
| `visible_result` | 首次 terminal 兼容 ToolMessage/拒绝文本，用于精确回读 |
| `transport_json` | 首次 terminal transport projection，用于 HTTP/SSE 回读 |
| `undo_json` | 可选、已验证的现有 undo payload |
| `result_sha256` | 对持久结果 envelope 的完整性摘要 |
| `failure_category` | 仅固定 ToolFailure 分类 |
| `failure_code` | 受控稳定 code；不保存异常文本 |
| `delivery_status` | `pending` / `completed` / `failed` / `not_applicable` |
| `delivery_failure_code` | 固定安全 code，不保存 Provider/异常原文 |
| `created_at` | proposal 创建时间 |
| `approved_at` | effective input 被批准时间 |
| `claimed_at` | 本次原子提交中的 claim 时间 |
| `rejected_at` / `committed_at` / `failed_at` | 对应终态时间 |
| `delivered_at` | 后续说明成功持久化时间 |
| `updated_at` | 每次合法状态变化更新时间 |

数据库约束：

- primary 必须有 `tool_call_id`，compensation 必须有 `parent_operation_id`；
- terminal 字段必须与 `status` 一致；
- fingerprint 格式固定为 `hmac-sha256:<64 lowercase hex>`；
- `failure_category` 只能来自 ToolFailure 闭集；
- `result_json` 与 `visible_result` 各自 UTF-8 上限 1 MiB；
- `transport_json` 上限 256 KiB；
- `undo_json` 上限 64 KiB；
- `failure_code` 上限 128 ASCII 字符；
- primary 对 `(conversation_id, tool_call_id)` 建立部分唯一索引，防止同一已持久 ToolCall 被分配两个 Operation；
- `(parent_operation_id, operation_role)` 对 compensation 建立部分唯一索引；
- terminal 结果更新使用 status CAS，不能覆盖首次结果。

`parent_operation_id` 对同表使用 FK；primary 的 `parent_operation_id` 必须为空，compensation 的 parent 必须是 committed primary。`agent_run_id` 只作为有界关联引用，不建立跨 fail-open Journal 的外键，否则 Journal 缺失或清理会反向阻塞业务写入。

terminal 字段组合使用数据库 CHECK 固定：rejected 不得有 input/claim/commit/failure 字段，但必须有 rejection envelope、摘要和 rejected 时间；committed 必须有 input fingerprint、result envelope、摘要和 committed 时间；failed 必须有 input fingerprint、固定 failure category/code、result envelope、摘要和 failed 时间。`approved_at/claimed_at` 只允许 committed/failed；首次 terminal envelope 一经写入不可变。

1 MiB 结果边界在领域 SAVEPOINT 提交前验证。超界时回滚领域变更并形成稳定 `failed / operation_result_too_large`，不会出现领域已写入但结果无法回读。

### 7.2 `write_operation_transitions`

| 字段 | 语义 |
| --- | --- |
| `id` | UUID 主键 |
| `operation_id` | FK → `write_operations.id` |
| `seq` | 从 1 递增，`(operation_id, seq)` 唯一 |
| `state` | `proposed` / `approved` / `rejected` / `claimed` / `committed` / `failed` |
| `created_at` | transition 时间 |

Transition 不保存参数、结果、异常、用户反馈或任意 facts。正常批准写入最终持久序列固定为：

```text
1 proposed
2 approved
3 claimed
4 committed | failed
```

`approved`、`claimed` 与 terminal 在同一 SQLite commit 中持久化。它们是完整审计序列，而不是可被其他进程观察和抢占的中间租约。崩溃时三者一起回滚，Operation 保持 `proposed`。

### 7.3 Conversation 私有列

```text
pending_operation_id TEXT NOT NULL DEFAULT ''
last_write_operation_id TEXT NOT NULL DEFAULT ''
```

`pending_operation_id` 与 pending tool identity 一起 CAS；所有 clear/replace/claim 路径必须同时匹配和维护它。`last_write_operation_id` 只关联现有 undo 控制，不对外替代 `last_write_undo_json`。

旧库中迁移前已经存在的 Pending Action 保持可确认。第一次读取/确认时，Repository 在同一事务中为它创建 proposal Operation 并填入 `pending_operation_id`。不在迁移脚本中复制或长期扫描 `pending_args`。

## 8. Ledger HMAC Key Domain

Ledger fingerprint 不能使用普通 SHA-256 暴露低熵状态、ID、薪资或文本候选，也不能依赖 fail-open Journal key。新增独立且强制的 Ledger HMAC key domain：

```text
write-operation-ledger.key
```

要求：

- 原子创建、并发创建保护、权限收紧和备份排除沿用第一期 keyring 的成熟实现；
- 数据库尚无 Operation 时允许首次创建；
- 已有 Operation 但 key 缺失、损坏或 key id 不匹配时，Agent 写入 fail-closed，不得静默生成新 key；
- 应用仍可启动并提供读工具、手工 UI 与普通非 Agent API；
- key、原始参数和 HMAC 输入不得进入日志、Journal、错误响应或测试资产；
- 本期不实现 key rotation。

## 9. Operation 身份

### 9.1 创建

Agent 选中写 ToolCall 并形成 Pending Action 时，由服务端生成 UUIDv4 `operation_id`。它进入 `PendingAction` 的安全控制字段，但不进入 Provider Tool Schema 或模型消息正文。

proposal 持久化必须原子完成：

```text
assistant ToolCall message
+ Conversation pending identity / pending_operation_id
+ write_operations(proposed)
+ transition(proposed)
```

任一步失败则整个事务回滚，不向客户端返回一个没有 Ledger 的确认卡。

确定性 Legacy Pending Action 同样在服务端创建时获得 operation id。澄清态尚不是可执行 proposal，不提前创建 Operation；澄清完成并真正写入 Pending 时才创建。

### 9.2 绑定字段

Operation 同时绑定：

```text
conversation_id
tool_call_id
tool_name
proposal_fingerprint
confirmation_fingerprint
agent_run_id（若可用）
```

批准/编辑后再绑定 `input_fingerprint`。任一不匹配返回稳定 conflict/stale，executor 为零次。`operation_id` 永远由服务端生成；客户端只能回显，不能选择新的 id 来进入 executor。

### 9.3 外部传输

Pending Action JSON 增加 `operation_id`。新版前端在同步和 SSE confirmation 请求中原样回显：

```json
{
  "conversation_id": 42,
  "operation_id": "00000000-0000-4000-8000-000000000000",
  "confirmation_token": "<existing token>",
  "approved": true,
  "edited_args": {}
}
```

后端为迁移中的旧客户端保留窄兼容：当 live Pending 仍存在时，缺少 `operation_id` 可使用服务端 `pending_operation_id`；Pending 已清除后的 terminal replay 必须携带 operation id。该兼容不允许客户端工具名决定 Legacy 路由。

请求继续使用现有 `edited_args` 语义，不新增 Provider 参数：

- live Pending 存在时，服务端从可信 proposal args 加 `edited_args` 重建 effective arguments；
- terminal replay 且 `edited_args` 字段存在并非 `null` 时（包括空 object），按请求中的编辑值重新计算 effective HMAC；
- terminal replay 且 `edited_args` 缺失或为 `null` 时，只在已存 `input_fingerprint == proposal_fingerprint` 时接受；
- terminal 表明首次执行使用过编辑值、但 replay 请求没有相同编辑值时返回 `operation_input_conflict`。

因此 Pending 清除后仍能验证未编辑批准，同时不会为了 replay 在 Ledger 保存原始参数。客户端不得提交完整 Tool args 来替代服务端 proposal，也不能借 replay 改变 effective input。

## 10. Repository 与 Unit of Work 边界

### 10.1 `WriteOperationCoordinator`

Coordinator 是唯一能够把 Operation 从 proposed 推向 terminal 的组件。它持有业务 `SessionFactory`、Ledger Repository、context binder 和 Ledger key domain。

公共结果固定为瞬态对象：

```python
OperationExecution = OperationCommitted | OperationFailed | OperationReplay | OperationUnknown
```

这些对象不得进入 LangGraph checkpoint。`ToolExecutionRecord` 增加 `operation_id` 与 `replayed`，仍保持瞬态和禁止通用序列化。

### 10.2 Session-bound Repository

以下领域边界增加显式 `bind(session)` 或等价的 `*_in_session` 核心方法：

```text
ApplicationsRepository
ApplicationEventsRepository
NotesRepository
OffersRepository
ResumesRepository
ApplicationJDService
ApplicationOutcomesRepository
ChatRepository confirmation claim helpers
```

约束：

- 原有 UI/API 公共方法继续自己创建 Session 和 commit，外部行为不变；
- bound 模式复用 Coordinator 的 Session，只允许 query/add/execute/flush；
- bound 模式不得调用 commit、rollback、close 或另一个 `BEGIN IMMEDIATE`；
- ToolExecutionContext 在执行时创建一个绑定 Session 的副本，Catalog 和原始 context 不变；
- executor 不接触 Session 参数，继续通过 Repository 边界工作；
- 源码/AST 门禁禁止 15 个 operation executor 调用网络、Provider、文件写入或未绑定写 Repository。

不为全仓库强行引入统一 UoW。只改造本期 15 个 executor 实际需要的领域方法，并保留各 Repository 当前公共接口。

### 10.3 SAVEPOINT

Coordinator 的外层事务持有 Pending claim、Ledger transitions 和最终 terminal。领域 executor 位于 SAVEPOINT 内：

- success：flush 领域变更，编码 result/transport/undo，释放 SAVEPOINT，写 committed；
- 已声明普通 `Exception`：回滚 SAVEPOINT，映射固定 ToolFailure，写 failed；
- 未声明普通 `Exception`：回滚 SAVEPOINT，写 `internal_error / executor_exception`；
- `BaseException`：回滚整个外层事务并继续传播，不形成虚假 failed；
- mandatory result codec、canonical JSON 或 result size 校验失败：回滚 SAVEPOINT，写固定 failed；
- compatibility renderer 失败：保持成功 Outcome，使用固定安全 fallback 作为 `visible_result` 并标记 delivery failure；
- transport projector 失败：保持成功 Outcome，保存固定最小 transport fallback 并标记 delivery failure；
- undo projector 失败：保持成功 Outcome，保存空 undo 并标记 delivery failure；
- 上述任何失败都不得再次调用 executor。

## 11. Pipeline 时序

### 11.1 等待确认

```text
prepare_call()
→ validation / capability / binding / read-only preflight
→ create server operation_id
→ atomic persist proposal + Pending
→ tool.proposed / approval.requested（Journal fail-open）
→ executor 0 次
```

### 11.2 拒绝

拒绝仍不重新 `prepare_call()`：

```text
load trusted Pending + operation_id
→ verify existing token / Pending identity
→ BEGIN IMMEDIATE
→ operation proposed CAS
→ transition rejected
→ clear Pending / claim state
→ COMMIT
→ persist/return rejection delivery
→ executor 0 次
```

原始 rejection feedback 不进入 Ledger。

### 11.3 批准或编辑后批准

```text
load trusted Pending + operation_id
→ prepare_call(effective args)
→ mutable recheck
→ BEGIN IMMEDIATE
→ load operation and verify identity
→ if terminal: replay, executor 0 次
→ Pending claim CAS in the same Session
→ create ExecutionAuthorization bound to operation_id + effective args digest
→ authorization match
→ append approved / claimed transitions
→ project tool.started in the owned transaction
→ SAVEPOINT
→ executor(bound ToolExecutionContext) exactly once in this attempt
→ project result / transport / undo
→ append committed | failed
→ project tool.completed | tool.failed
→ COMMIT domain + Ledger + retained Journal events
```

claim、authorization 或 Operation identity 失败时，不写 `tool.started`，executor 为零次。

### 11.4 Read Tool

Read Tool 不创建 Operation，不经过 Ledger，不获取业务写锁，Pipeline 行为保持第二期原样。

## 12. Journal 集成

第一期事件 Schema 不升级，不增加 `operation.*` 事件，也不把 operation id 塞入未允许的 facts。Ledger 通过 `agent_run_id + tool_call_id + tool_name` 与 Journal 关联。

普通 Journal 仍使用独立短超时 Pool。写 Operation 已持有 SQLite write transaction 时，另一个 Journal 连接无法可靠插入 `tool.started`。因此 SafeRunRecorder 增加一个窄的、可选的同 Session 投影入口：

- 仅用于本期 `tool.started` 和 terminal 事件；
- 事件仍经第一期冻结的 preparer、HMAC、payload size 和 dedupe 校验；
- 每次投影置于独立 SAVEPOINT，失败只回滚 Journal 投影，不污染外层业务事务；
- Null/degraded/budget-exhausted recorder 直接跳过；
- Journal 失败仍不能改变 Ledger、领域结果或 executor 次数；
- replay 不伪造 `tool.started/completed/failed`。

这保持第一期 fail-open 性质，同时避免每个业务写事务因为 SQLite 自锁而必然降级。

## 13. Result、Undo 与隐私

### 13.1 为什么需要持久结果

update/delete 后领域行可能继续变化或消失，仅保存 ID 无法回读第一次 ToolMessage。Ledger 因此必须保存第一次结果投影。它与领域表位于同一个业务数据库和备份域，是业务幂等数据，不是诊断 Journal。

### 13.2 持久内容边界

允许：

- 15 个受控 adapter 产生的 JSON result；
- 已冻结的兼容 ToolMessage 文本；
- transport projector 的既有 payload；
- 4 类现有、结构化且有界的 undo payload；
- 固定 failure category/code、时间和引用 ID。

禁止：

- 原始 Tool args；
- Prompt、完整 Conversation、模型回答；
- 原始异常文本、stack trace、exception repr；
- credential、Provider request body、API key；
- 任意 adapter 未声明的对象或 pickle；
- 把 result/undo 复制到 Journal 或普通日志。

每个 WriteContract 使用封闭 codec。只接受 JSONValue，canonical 编码禁止非有限数字。`result_sha256` 在回读时验证；不匹配返回 `operation_integrity_error`，绝不重新执行。

Resume 写工具的首次结果可能包含领域数据库中已经存在的简历内容。本期为了精确回读允许其出现在 Ledger result，但仅保存在同一业务数据库、受 1 MiB 上限约束，不进入日志/Journal/测试 golden。若结果超界，整个领域 SAVEPOINT 回滚。

### 13.3 Undo

现有 undo seed 和 result projector 移入 WriteContract，在领域事务内读取 before、在 executor 后生成 expected-after。`undo_json` 与 committed 一起提交。Conversation 的 `last_write_undo_json` 和 `last_write_operation_id` 在后续 delivery CAS 中更新；若 delivery 暂时失败，terminal replay 会用 Ledger undo 收敛。

## 14. Terminal Replay 与交付收敛

### 14.1 回读规则

确认入口在返回 stale 前先检查请求携带的 operation id：

- committed + identity/effective fingerprint 一致：返回首次结果，executor 0，Provider 0；
- failed + identity/effective fingerprint 一致：返回首次固定失败，executor 0，Provider 0；
- rejected + decision 一致：返回首次拒绝结果，executor 0，Provider 0；
- terminal 但 identity、decision 或 fingerprint 不一致：409 conflict；
- proposed：继续正常 claim/execute；
- integrity 校验失败：500 `operation_integrity_error`，executor 0；
- Ledger 暂时不可读：503 `operation_result_unknown` 且 `retryable=true`，executor 0，客户端保留原请求重试。

### 14.2 Pending 已清除

response 丢失后 Pending 可能已经清除。新版客户端仍持有 `operation_id + confirmation_token + effective edit request`，后端直接从 Ledger 回读，不要求重新存在 Pending，也不重新进入 LangGraph/Provider。

### 14.3 Pending 尚未清除

若领域 transaction 已 committed 但进程在 confirmation result sink 前退出，Pending 仍携带同一 operation id。重试从 Ledger 得到 terminal，使用现有 Pending CAS 持久化已保存的 ToolMessage、undo 和确定性 fallback assistant message，再清除 Pending。它不调用 executor 或 Provider。

active confirmation claim 尚未过期时，不抢占可能仍在交付的 owner；返回 retryable conflict。claim 过期或已知 owner 放弃后可收敛。由于 Ledger 已 terminal，收敛只处理消息交付，不再涉及业务写入。

### 14.4 Delivery 状态

领域 terminal 后：

- ToolMessage/Pending CAS 成功且后续 assistant 消息持久化：`delivery_status=completed`；
- Provider follow-up 明确失败：`delivery_status=failed` + 固定 code；
- 进程退出或结果未知：保持 `pending`；
- deterministic rejection/compensation 无 Provider follow-up时使用 `not_applicable` 或 completed。

Delivery 更新是 terminal 之后的独立 CAS，不能改变 committed/failed/rejected，也不能触发 executor。`agent_run_id` 允许将 committed Operation 与随后失败的 Run 对照，从而回答“领域写入成功，但说明生成失败”。

## 15. 确认与 Operation 并发

SQLite 使用 `BEGIN IMMEDIATE` 获取单 writer。并发相同 operation id：

1. 两个请求都可以在事务外完成只读 prepare；
2. 第一个获得 writer lock，验证 proposed，执行并提交 terminal；
3. 第二个获得 lock 后看到 terminal，只回读；
4. 如果等待 writer lock 超时，第二个返回 `operation_busy/result_unknown`，executor 为零次。

不同 operation id 继续遵守 SQLite 现有单 writer 行为。本期不提高写吞吐，不在写锁内执行 Provider、网络或文件 I/O。

## 16. Commit 结果未知

不能把 `session.commit()` 抛错简单当成“肯定没提交”。Coordinator 在 commit 异常后：

1. 丢弃当前 Session；
2. 用新 Session 只读查询 operation id；
3. 若 terminal 和完整性校验成立，返回 replay；
4. 若仍是 proposed，返回 503 `operation_not_committed` 且 `retryable=true`，不在同一请求再次调用 executor；
5. 若数据库不可读，返回 `operation_result_unknown`，不进行任何自动 retry/fallback executor。

因此一次 HTTP 请求内 executor 仍最多调用一次；只有后续请求在能够证明前一事务整体未提交时才允许重新尝试本地事务。

## 17. Legacy 集成

3 个 Legacy Adapter 保持：

- 不进入 Typed Catalog；
- 不进入 Provider Schema；
- 只能由服务端 deterministic action 创建；
- 确认恢复先读取 server Pending，再按封闭名称路由；
- 保留已有参数校验、业务 CAS、idempotency key、错误文案和返回字符串。

需要重构 `ApplicationJDService` 和 `ApplicationOutcomesRepository` 的三个写方法，使其核心逻辑能在外部 Session 中执行。原有领域 idempotency key/unique constraint 继续存在，作为 Ledger 之外的领域级第二道保护。Ledger replay 时不再次调用这些领域方法。

## 18. 补偿 Operation

`undo-last-write` 从 Conversation 读取 `last_write_operation_id` 和 Ledger 中的 immutable `undo_json`，不信任客户端 undo payload。新版前端请求携带 `parent_operation_id`；live last-write 仍存在时后端可为旧客户端使用服务端字段，last-write 已清除后的 replay 必须携带 parent id。补偿 operation id 使用服务端 UUIDv5，由原 operation id 和固定 compensation kind 确定；同一原始 Operation 重试得到同一补偿 id。

补偿与主写相同地在一个事务内完成：

```text
proposed → approved → claimed → committed | failed
```

它调用现有 conditional delete/restore CAS 的 Session-bound 版本。第一次补偿成功后：

- Ledger 记录 committed result；
- Conversation 仅在匹配原 operation id 时清除 last undo；
- 响应丢失后的重试回读“已撤销”结果；
- 不再次执行 delete/restore。

如果领域记录已被其他操作修改，补偿 Operation 稳定 failed/conflict；不会覆盖新状态。

## 19. API、SSE 与前端

### 19.1 Provider

Provider 看到的 25 个工具完整 envelope、名称、顺序、description 和 Schema 必须与第二期 golden 完全相同。`operation_id` 不进入模型工具参数。

### 19.2 HTTP

以下 payload 增加 additive `operation_id`：

- pending confirmation；
- confirm success/failure/rejected；
- write-related error details；
- undo success/failure。

用户可见兼容 ToolMessage 和现有 `write_status`/undo 语义保持不变。terminal replay 明确返回 `replayed: true`；第一次执行为 false 或省略。

### 19.3 SSE

sync/stream 共用同一个 Operation coordinator 和 replay service。SSE 的 tool/result/final response 增加同一 operation id；断线重试不会尝试从 Ledger 重放旧 SSE seq，只返回一个新的请求流和已持久 terminal result。本期仍不实现 SSE reconnect/replay。

### 19.4 Frontend

前端只做隐藏控制字段传递：

- PendingAction 类型保存 operation id；
- approve/edit/reject 的同步和流式请求原样回显；
- 网络失败时保留同一 operation id、token 和 edited args；
- terminal replay 按普通成功/失败渲染；
- undo 请求只回显 `parent_operation_id`，使用服务端关联的 immutable undo，不接受前端生成的领域 payload。

不新增 Operation UI、历史页或调试面板。

## 20. 错误语义

新增固定 Ledger code：

```text
operation_unavailable
operation_busy
operation_identity_conflict
operation_input_conflict
operation_result_unknown
operation_not_committed
operation_integrity_error
operation_result_too_large
operation_not_transactional
operation_delivery_failed
```

映射原则：

- proposal/claim 前 Ledger 失败：executor 0，写操作 fail-closed；
- executor 普通异常：executor 1，领域 SAVEPOINT 回滚，稳定 failed；
- BaseException：传播，整个事务回滚；
- Journal 失败：不改变 Operation outcome；
- mandatory result codec/size 失败：领域 SAVEPOINT 回滚，稳定 failed；
- renderer/transport/undo projector 失败：保持已经确定的 Outcome，持久安全 fallback/空 undo 和 delivery failure；
- commit 结果未知：不自动重跑；
- delivery 失败：保留 committed，返回/持久化 deterministic fallback；
- replay 投影失败：使用已持久 `visible_result/transport_json`，不调用当前 renderer 或 executor。

日志只允许：operation id、tool name、状态、固定 code、耗时和安全计数。禁止 result、undo、参数、token、异常正文。

## 21. 迁移与兼容

`0026` 必须覆盖：

- fresh database；
- 从第二期 `0025` 升级；
- 重复 `init_database()` 幂等；
- 已有空 Pending；
- 已有非空 Pending 的 lazy proposal adoption；
- conversation 删除后 Operation 保留；
- 现有 0024 Journal 和 0025 confirmation claim 数据不变。

本分支尚未发布，因此可以直接调整 0025 之后的模型/迁移顺序，但 migration version 仍固定记录为独立 `0026_write_operation_ledger`，不重写 0024/0025 的语义。

Ledger table 是业务真值，迁移失败不能 fail-open。数据库初始化失败时必须明确阻止 Agent 写入；不得用内存 Ledger 或旧 executor fallback 继续写。

## 22. 机械契约

新增只读 manifest，测试固定：

```text
12 typed primary
3 legacy deterministic primary
4 compensation
```

机械门禁必须证明：

- 每个 `kind=write` 的 ToolSpec 恰有一个 WriteContract；
- read ToolSpec 不得声明 WriteContract；
- 3 个 Legacy 名称恰好各有一个 Ledger adapter，仍不在 Provider manifest；
- 4 个 undo kind 恰好各有一个 compensation adapter；
- 没有 write executor 绕过 Coordinator；
- Agent/API 不直接调用 15 个领域写核心；
- bound Repository 路径不存在 commit/rollback/新 Session；
- executor 事务内不存在 Provider、HTTP、浏览器、文件写入；
- 不存在 `ledger_enabled` feature flag、shadow write、dual write、memory fallback 或旧路径 fallback；
- Provider 第二期 golden byte/canonical 等价；
- Journal 第一期开集不变；
- checkpoint 中不存在 Ledger Session、Coordinator、OperationExecution、result、undo 或 key。

## 23. 测试策略

### 23.1 模型与迁移

- 表、列、索引、CHECK、FK、UTF-8 byte 上限；
- fresh / 0025 upgrade / repeated init；
- old live Pending lazy adoption；
- terminal immutability；
- transition seq 与固定生命周期；
- HMAC key create/race/permission/missing-existing-key failure。

### 23.2 Repository / UoW

对每个领域 adapter 验证：

- public Repository 仍自己 commit；
- bound Repository 不 commit；
- domain + Ledger 同一事务成功；
- executor 后、terminal 前注入崩溃时两者都回滚；
- terminal 写入后、commit 前崩溃时两者都回滚；
- mandatory result codec 或 result size 校验失败时领域回滚；
- exception savepoint 回滚后 failed 可提交；
- BaseException 不形成 terminal。

### 23.3 并发与 crash matrix

- 两线程/两连接同 operation，只产生一个领域 commit 和一个 executor winner；
- committed loser 回读；
- failed/rejected loser 回读；
- 不同 input/tool/conversation/decision 冲突且 executor 0；
- SQLite busy 返回 result unknown，不自动 retry executor；
- commit exception 后用新连接判定 committed/proposed/unavailable 三种结果；
- 进程在领域 commit 后、Pending clear 前退出，下一请求只收敛 delivery。

### 23.4 15 个主写 golden

每个操作至少覆盖：

- first success；
- same-operation sync replay；
- same-operation SSE replay；
- result/transport/undo 等价；
- domain row/count 只变化一次；
- executor 和 Provider 调用次数；
- declared failure stable replay；
- operation/transition 精确行。

已有领域 idempotency 的 3 个 Legacy 还要覆盖 Ledger operation id 与领域 idempotency key 的交叉冲突。

### 23.5 HITL

- approve / edit / reject；
- edit 后 effective HMAC 与 replay body 匹配；
- 拒绝不 prepare、不 executor；
- missing/foreign/malformed operation id；
- old client live-Pending compatibility；
- Pending 已清除的 terminal replay；
- active/stale claim 的 delivery 收敛；
- sync/stream 完全一致。

### 23.6 Journal 与隐私

- first execution 保持 proposed → started → completed/failed；
- replay 不伪造 started/terminal；
- 同 Session Journal SAVEPOINT 失败不影响 domain/Ledger；
- Ledger/日志/Journal 不含 args、exception、token、Prompt、回答；
- synthetic fixture 不保存真实用户内容或 key。

### 23.7 补偿

- 四种 undo first commit + replay；
- 原领域状态变化后的 stable conflict；
- parent/child 唯一；
- undo response loss 不产生第二次领域写；
- Conversation last undo 只由匹配 parent 清除。

## 24. 发布门禁

实现完成前必须通过：

- 固定 baseline + immutable allowlist；
- 15/4 operation manifest、并集和重复检查；
- Provider 第二期 golden、Tool outcome golden、Journal sequence golden；
- 后端全量分组 manifest/duplicate/skip/aggregate；
- 前端全量分组 aggregate；
- Ruff、Mypy、frontend build、static smoke、local verify；
- 一次受控 real-AI verify；
- 本地浏览器 Chat 闭环：approve、edit、reject、sync、SSE、response-loss retry、undo retry；
- DB 证明领域行一次、Ledger terminal 一次、transition 序列正确、Pending 收敛；
- Provider/Tool 调用次数证明 replay 为零；
- 独立 CR 无 P0/P1/P2；
- allowlist、未跟踪文件、`git diff --check` 和干净工作区；
- 发布报告明确内部破坏性重构、15/4 边界、业务提交 exactly-once 的精确定义及外部副作用非目标。

## 25. 破坏性变化

允许并计划进行以下内部破坏性重构：

- PendingAction、ExecutionAuthorization 和 ToolExecutionRecord 增加 operation identity；
- write ToolSpec 必须声明 WriteContract；
- Pipeline write 分支必须经过 Coordinator；
- 相关 Repository 拆出 Session-bound 核心；
- confirmation claim 改为外层业务事务内 CAS；
- undo 从 API helper 移入 compensation adapter；
- 旧的“executor commit 后再推断 undo/result”分支删除；
- 任何绕过 Ledger 的 Agent write 路径删除，不保留 feature flag 或 fallback。

外部 Provider Tool 契约保持不变。HTTP/SSE 只增加 operation id/replayed 等 additive 控制字段，现有用户可见文本和领域语义保持兼容。

## 26. 验收结论标准

第三期只有同时满足以下条件才能宣称完成：

1. 12 个 Typed 写工具全部通过 Ledger；
2. 3 个 deterministic Legacy 写动作全部通过 Ledger，且仍模型不可见；
3. 4 类现有补偿写入全部通过子 Operation；
4. 相同 operation id 的领域事务最多 committed 一次；
5. commit 后 HTTP/SSE/进程丢失能回读首次结果，executor 和 Provider 均不重跑；
6. domain/Ledger 原子性和 crash matrix 通过；
7. Journal 仍 fail-open，Ledger 写入 fail-closed；
8. Provider、HITL、Pending、CAS、业务结果与调用次数满足兼容 golden；
9. 没有未列明的 Agent write bypass；
10. 独立复审和完整发布门禁通过。

完成第三期后，第四期 Context Projector 才能使用 Ledger 的 committed/failed/replayed 数据区分“模型提出动作”和“业务真正提交”，但第四期不属于本设计。
