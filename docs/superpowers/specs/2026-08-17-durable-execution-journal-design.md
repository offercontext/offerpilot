# Durable Execution Journal 设计

日期：2026-08-17

状态：待复审

分支：`feat/20260817-durable-execution-journal`

固定基线：`b0a5697`（叠加于 Harness Reliability Contract）

## 1. 背景与问题

OfferPilot 已具备 Conversation、ChatMessage、Pending Action、Proposal Attempt、幂等键、lease、CAS、fencing、SSE 与脱敏 Harness，但这些结构分别服务于聊天展示、业务一致性、恢复和验收，尚不能回答一条 Agent 请求完整经历了什么。

当前因果信息分散在以下位置：

- `src/offerpilot/api.py` 的普通聊天、流式聊天与确认路由；
- `src/offerpilot/ai/agent.py` 的模型循环、工具调用和人工确认；
- Conversation 与 ChatMessage 中混合保存的对话、工具调用和工具结果；
- 进程内的 SSE 状态；
- 各业务 Attempt、恢复策略和脱敏 Harness 诊断。

这导致故障排查必须跨日志、消息、Attempt 和浏览器审计人工拼接，而且进程退出后部分运行时信息不可恢复。后续要建设统一 Tool Pipeline、Write Operation Ledger 和 Context Projector，也缺少稳定的运行身份与因果关联基础。

本项目新增一个小型、持久化、失败开放的 **Durable Execution Journal**。它记录已经发生的运行事实，供内部诊断和 Harness 重建因果链使用。

它不是事件溯源系统，不替代现有业务事实源，也不承担恢复、授权、重试或 SSE 重放。

## 2. 目标与非目标

### 2.1 目标

1. 为一次逻辑 Agent 运行提供稳定 `AgentRun` 身份。
2. 区分逻辑 Run、物理请求 Segment 和模型调用 Step。
3. 持久记录路由、上下文摘要、模型调用、工具调用、人工确认和终态之间的因果关系。
4. 普通、流式、确定性路由和确认恢复使用同一事件语义。
5. Journal 故障时业务 fail-open，且故障本身可观察。
6. 不保存 Prompt、用户正文、模型正文、附件内容或密钥。
7. 提供内部确定性读取模型，重建因果 trace 并识别不完整运行。
8. 为后续 Tool Pipeline、Write Operation Ledger 和 Context Projector 提供稳定关联点，但不提前实现这些能力。

### 2.2 非目标

本期明确不实现：

- 事件溯源、状态回放或从 Journal 恢复业务状态；
- SSE 断点续传或持久化 Token 流；
- 后台任务队列、多 Agent 编排或分布式调度；
- Tool 输入输出协议重构；
- Write Operation Ledger；
- 能力裁剪、审批策略重构或 Context Projector；
- 完整 Prompt、消息正文、JD、简历、附件或模型输出归档；
- 新增公开 API、CLI 页面、设置页或前端 UI；
- 声称 Journal 与各业务写入具有跨 Repository 原子事务；
- 拆分整个 `api.py` 或重写现有 Agent Runtime。

## 3. 方案选择

### 3.1 采用：增量式 Durable Execution Journal

在现有执行路径旁增加窄 Recorder，通过稳定 Run ID 和版本化事件记录事实。业务事实源和恢复契约保持不变。

优点：

- 改动可控，可在不改变产品行为的前提下单独验收；
- 为后续重构建立可观察基线；
- Recorder 可 fail-open，也可通过 kill switch 完全关闭；
- 不把当前耦合一次性迁移到新框架。

### 3.2 不采用：完整事件溯源

以 Event Store 作为 Conversation、工具写入和确认状态的唯一事实源，理论上能回放全部状态，但会同时改变持久化、恢复、迁移和删除语义，范围过大。OfferPilot 当前不需要该复杂度。

### 3.3 不采用：仅扩展日志与 Trace JSONL

继续向诊断日志写入字段，实施成本较低，但无法提供数据库级顺序、并发去重、确认跨请求关联和进程退出后的稳定读取，不足以支撑后续 Runtime 重构。

## 4. 身份模型

```text
Conversation
└── AgentRun：一次逻辑运行
    ├── ExecutionSegment：一次物理 HTTP/SSE/确认恢复请求
    │   ├── ModelStep 1
    │   ├── Tool Call A
    │   └── ModelStep 2
    └── ExecutionSegment：后续确认、编辑确认或拒绝请求
```

### 4.1 AgentRun

一次用户输入触发一个逻辑 Run。若该 Run 进入人工确认，后续确认、编辑确认或拒绝继续使用原 `agent_run_id`，不得创建第二个逻辑 Run。

### 4.2 ExecutionSegment

每个物理请求生成新的 UUID `execution_segment_id`，包括：

- 首次普通聊天请求；
- 首次流式聊天请求；
- `/api/chat/confirm`；
- `/api/chat/confirm/stream`；
- 编辑后确认或拒绝。

第一期不建立 Segment 表。Segment ID 作为 AgentEvent 和 AgentContextSnapshot 的必填关联字段。

### 4.3 ModelStep

同一 Segment 内每次真正发起模型请求时递增整数 `model_step`。确定性路由可以没有 ModelStep，并明确记录 Provider 调用为零。

### 4.4 序号边界

`AgentEvent.seq` 是同一 Run 内的持久事件序号，与 SSE seq 完全独立。禁止将两者映射或复用。

## 5. 数据模型

当前最新迁移为 `0023_immersive_interview_studio`。本项目新增迁移：

```text
0024_durable_execution_journal
```

迁移只新增三张表，不修改现有 Conversation、ChatMessage、Pending Action 或业务表字段。

### 5.1 AgentRun

建议字段：

| 字段 | 语义 |
|---|---|
| `id` | UUID 字符串，逻辑 Run 身份 |
| `conversation_id` | Conversation 外键，删除 Conversation 时级联清理 |
| `input_message_id` | 初始用户消息 ID，可空，不保存正文 |
| `trigger_kind` | `user_message / confirmation / deterministic` 等固定枚举 |
| `context_type` / `context_ref` | 当次运行上下文身份 |
| `interaction_mode` | `sync / stream` |
| `route_kind` | `model / deterministic / unknown` |
| `status` | 业务运行状态 |
| `waiting_tool_call_id` | 等待确认时的稳定关联 ID，可空 |
| `next_seq` | 下一个事件序号，由数据库原子更新 |
| `recording_status` | `healthy / degraded` |
| `recording_error_count` | Journal 内部错误计数 |
| `failure_code` | 脱敏的最终失败类别，可空 |
| `started_at / updated_at / finished_at` | UTC 时间 |

Run 状态固定为：

```text
running
waiting_confirmation
completed
failed
cancelled
timed_out
```

允许转换：

```text
running -> waiting_confirmation | completed | failed | cancelled | timed_out
waiting_confirmation -> running | failed | cancelled | timed_out
```

所有终态不可再次转换。`status` 与 `recording_status` 相互独立；业务可以成功而记录降级。

### 5.2 AgentEvent

建议字段：

| 字段 | 语义 |
|---|---|
| `id` | UUID 字符串 |
| `run_id` | AgentRun 外键，Run 删除时级联 |
| `seq` | Run 内持久顺序 |
| `dedupe_key` | 同一事实的稳定去重键 |
| `event_type` | 固定事件类型 |
| `schema_version` | 事件 payload 版本，首期为 1 |
| `execution_segment_id` | 物理请求身份 |
| `model_step` | 模型调用序号，可空 |
| `source_ref_type / source_ref_id` | Message、Tool Call、Operation 等稳定关联，可空 |
| `payload_json` | 白名单、脱敏、限长 canonical JSON |
| `payload_digest` | canonical payload SHA-256 |
| `created_at` | UTC 时间 |

数据库约束：

```text
UNIQUE(run_id, seq)
UNIQUE(run_id, dedupe_key)
```

相同 dedupe key 和相同 payload digest 返回原事件；相同 key 但事实不同属于 Journal 冲突，SafeRunRecorder 将记录降级，不得静默接受。

### 5.3 AgentContextSnapshot

Context Snapshot 仅保存“使用了哪些上下文”的 manifest，不保存内容：

| 字段 | 语义 |
|---|---|
| `id` | UUID 字符串 |
| `run_id` | AgentRun 外键 |
| `execution_segment_id` | 物理请求身份 |
| `snapshot_kind` | `initial / confirmation_resume / model_input` |
| `model_step` | 关联模型调用，可空 |
| `manifest_json` | 来源 kind、稳定 ID、revision、路径类别与计数 |
| `input_digest` | 实际模型输入的 canonical SHA-256，不保存输入 |
| `estimated_token_count` | 可空的确定性估算 |
| `created_at` | UTC 时间 |

Context manifest canonical JSON 上限为 16 KiB；单个 Event payload canonical UTF-8 上限为 4 KiB。

## 6. Recorder 架构

### 6.1 分层

新增三个职责明确的组件：

1. `AgentRunRepository`
   - 创建 Run；
   - 原子分配 seq；
   - 追加事件和 Context Snapshot；
   - 在同一 Journal 事务中更新状态并追加状态事件。
2. `RunRecorder`
   - 面向 API 和 Agent 的窄接口；
   - 校验事件 schema；
   - canonicalize、脱敏、限长；
   - 构造稳定 dedupe key。
3. `SafeRunRecorder`
   - 捕获所有 Journal 异常；
   - 输出不含用户原文的结构化诊断；
   - best-effort 将 Run 标为 `degraded`；
   - 绝不改变原 API、SSE、Provider、工具和业务写入结果。

创建 Run 本身失败时使用 `NullRunRecorder` 完成请求，并记录 `journal_run_create_failed`。调用方不得直接操作 Journal 表或自行生成 seq。

### 6.2 窄接口

```python
start_run(...)
start_segment(...)
capture_context(...)
append_event(...)
transition(...)
mark_degraded(...)
```

生产默认启用内部开关：

```text
OFFERPILOT_AGENT_JOURNAL_ENABLED=true
```

关闭时使用 `NullRunRecorder`。不增加设置页或公开 API。开启与关闭的 HTTP、SSE、Provider、工具、ChatMessage 和业务写入必须一致，唯一区别是三张 Journal 表是否产生记录。

### 6.3 并发与原子序号

seq 必须通过数据库原子 `UPDATE ... RETURNING` 或等价 CAS 循环取得，并与事件插入处于同一短事务。状态转换和对应状态事件也必须位于同一 Journal 事务。

明确禁止：

- `MAX(seq) + 1`；
- 以进程内锁代替数据库并发控制；
- 先提交状态、再 best-effort 追加对应状态事件；
- 将 SSE 序号作为持久序号。

## 7. 事件契约

第一期只记录重建因果链必需的事件：

```text
run.started
segment.started
route.selected
context.captured

model.requested
model.completed
model.failed

tool.proposed
tool.started
tool.completed
tool.failed

approval.requested
approval.decided

assistant.persisted

run.waiting_confirmation
run.resumed
run.completed
run.failed
run.cancelled
run.timed_out
```

每个事件类型都有固定 `schema_version`、字段白名单与 payload 上限。未知字段、异常对象、非普通 JSON、超限内容和敏感字段拒绝写入并使记录降级，不做“尽量序列化”。

示例：

```json
{
  "event_type": "tool.completed",
  "schema_version": 1,
  "payload": {
    "tool_name": "save_application_jd_version",
    "tool_kind": "write",
    "outcome": "confirmation_required",
    "duration_ms": 824,
    "operation_id_hash": "sha256:...",
    "result_contract": "legacy_string_v1"
  }
}
```

现有工具仍返回字符串。本期将结果标记为 `legacy_string_v1`，不借机重构 `ai/tools.py`。

### 7.1 禁止持久化的内容

- Prompt 和消息正文；
- 模型完整响应或 Token delta；
- 工具完整参数与返回值；
- JD、简历、证据摘录、附件内容；
- API key、确认 token、幂等 key 原文；
- 未经白名单批准的异常字符串。

稳定关联使用内部 ID、分类字段、计数、长度、revision 和 hash。

### 7.2 记录时机

- `model.requested`：真正发起 Provider 请求前；
- `model.completed`：完整响应收到且基础解析完成后；
- `tool.started`：确定执行工具后；
- `tool.completed`：工具结果已经确定后；
- `approval.requested`：待确认动作成功持久化后；
- `approval.decided`：确认决定及业务结果成功持久化后；
- `assistant.persisted`：Assistant Message 保存成功后；
- `run.completed`：所有必要业务写入完成后。

进程异常退出时不补造失败事件。

## 8. 四条运行时序

### 8.1 普通回答

```text
run.started
segment.started
route.selected(model)
context.captured
model.requested
model.completed
assistant.persisted
run.completed
```

### 8.2 工具循环

```text
model.requested(step=1)
model.completed(step=1)
tool.proposed(call=A)
tool.started(call=A)
tool.completed(call=A)
model.requested(step=2)
model.completed(step=2)
assistant.persisted
run.completed
```

一次响应包含多个工具时，每个工具使用独立 `tool_call_id`。事件仅保存工具名、读写分类、耗时、结果类别、错误类别和脱敏 Operation 关联。

### 8.3 确定性路由

```text
run.started
segment.started
route.selected(deterministic)
context.captured
tool.proposed
approval.requested
run.waiting_confirmation
```

该序列明确证明 Provider 调用为零，不能与 Provider 失败混淆。

### 8.4 HITL 确认与恢复

首次请求持久化 Pending Action 后记录 `approval.requested` 和 `run.waiting_confirmation`。确认、编辑确认或拒绝通过既有 Pending Action、`waiting_tool_call_id` 和稳定内部 ID 找回原 `agent_run_id`，创建新 Segment，并依次记录：

```text
segment.started
run.resumed
approval.decided
assistant.persisted（如有）
run.completed 或 run.failed
```

确认 token、幂等键、Conversation、Pending Action、Attempt、lease、CAS 和 fencing 继续是业务事实源。Journal 只记录相关 ID 或 hash。

找不到原 Run 时，确认业务继续执行，并记录 `journal_run_missing` 诊断。Journal 写入失败时不得回滚已经成功的确认结果。

编辑确认只保存决定类型和新旧输入摘要指纹，不保存编辑原文。

## 9. 失败与不完整运行

- 已知 Provider、工具或业务失败：记录对应失败事件，再进入 `failed`；
- 客户端取消且服务端确认停止：进入 `cancelled`；
- 服务端明确判定超时：进入 `timed_out`；
- 进程崩溃、机器退出或强制终止：保留最后事件和 `running` 状态；
- 本期不实现后台清扫器，也不自动把旧 `running` 改成失败；
- 读取端将长期未结束且无终态事件的 Run 标记为“记录不完整”，而非业务失败；
- 业务成功但 Journal 部分失败时，Run 可以为 `completed + degraded`。

## 10. 内部读取模型

提供 Python 内部接口：

```python
reconstruct_agent_run(run_id: UUID) -> AgentRunTrace
```

返回：

- Run 身份、触发方式、业务状态与记录健康状态；
- 按 Segment 分组的物理请求；
- 每段中的 ModelStep、Tool Call 和 Approval；
- Context manifest 与输入指纹；
- Message、Pending Action、Operation 的稳定 ID 关联；
- 是否完整结束；
- 是否存在事件缺口、非法状态转换或记录降级。

该接口只用于测试、诊断和后续内部 Harness。它不得驱动业务恢复、授权、重试或写入，也不新增公开路由。

## 11. 与现有可靠性契约的关系

- `operation_id`：继续关联一次业务操作；
- `idempotency_key`：继续控制业务去重，Journal 不保存原文；
- Attempt、lease、CAS、fencing：继续决定谁能写入业务终态；
- SSE：继续负责实时传输，格式和 seq 不变；
- Harness Recovery Contract：继续决定错误恢复动作；
- Durable Journal：只解释这条链路已经发生了什么。

本分支叠加在 `b0a5697`，保留 Harness Reliability 的现有提交，不重写历史。

## 12. 文件边界

预计允许修改或新增：

```text
src/offerpilot/models.py
src/offerpilot/db.py
src/offerpilot/config.py
src/offerpilot/repositories/agent_runs.py

src/offerpilot/agent_runtime/__init__.py
src/offerpilot/agent_runtime/events.py
src/offerpilot/agent_runtime/journal.py
src/offerpilot/agent_runtime/trace.py

src/offerpilot/api.py
src/offerpilot/ai/agent.py

tests/test_agent_run_migrations.py
tests/test_agent_runs_repository.py
tests/test_agent_run_journal.py
tests/test_agent_run_trace.py
tests/test_ai_agent.py
tests/test_chat_api.py
tests/test_smoke.py

docs/superpowers/specs/2026-08-17-durable-execution-journal-design.md
docs/superpowers/plans/2026-08-17-durable-execution-journal.md
docs/reports/2026-08-17-durable-execution-journal-release-verification.md
```

禁止修改：

```text
web/**
src/offerpilot/ai/tools.py
现有业务 Repository
现有 Proposal / Attempt / lease / CAS 实现
SSE 公开事件格式
公开 API Schema
README.md
```

若实施中确认必须越过边界，应先修订设计与计划，不得以“顺手重构”为由扩大范围。

## 13. 测试与验收

### 13.1 Migration 与 Repository

- 空库创建；
- 当前 `0023` 数据库升级到 `0024`；
- 重复迁移；
- Conversation 与 Run 级联删除；
- 双 SQLite 连接并发追加，seq 唯一且连续；
- 相同 dedupe key、相同事实幂等返回；
- 相同 dedupe key、不同事实进入 degraded；
- 状态转换矩阵和终态不可变；
- 4 KiB payload 与 16 KiB manifest 的边界；
- 非法 JSON、异常对象和敏感字段拒绝。

### 13.2 Runtime 集成

- 普通非流式回答；
- 普通 SSE 回答；
- 确定性路由且 Provider 调用为零；
- 只读工具循环；
- 写工具进入等待确认；
- 确认、编辑确认、拒绝复用原 Run 并新增 Segment；
- 多轮工具与多次确认；
- Provider、工具和消息持久化失败；
- 客户端取消与服务端超时；
- 模拟进程中断后读取为不完整；
- Journal 创建、追加和状态更新分别故障时业务结果不变。

### 13.3 隐私与行为等价

- Journal 不包含 Prompt、用户原文、附件、JD/简历全文、模型正文、确认 token 或幂等 key 原文；
- Context 只保存 manifest、稳定 ID、revision、计数和 digest；
- 开启与关闭 Journal 时，HTTP 状态、响应体、SSE 序列、消息、业务写入以及 Provider/工具调用次数逐项一致；
- 读取模型可以确定性还原因果顺序；
- SSE seq 与 Journal seq 保持独立。

### 13.4 发布门禁

1. 后端五组完整门禁，校验 manifest、重复 node ID、允许 skip 和 aggregate；
2. 前端完整门禁，证明 SSE 与既有 UI 无回归；
3. Ruff、Mypy、生产构建、Smoke、Local Verify；
4. 本地受控 Provider 完成一条普通、工具、确认的完整因果链；
5. 以上全部通过后，最多执行一次既有 real-AI verify，不进行无界重试；
6. 非平凡代码独立复审；
7. 发布报告记录真实结果和剩余风险。

本期没有 UI 变化，因此不要求产品截图。若浏览器 Harness 用于验证 SSE，只保存脱敏网络审计，不把它包装成新功能截图。

## 14. 分提交策略

实施阶段拆成四个可独立复审的提交：

1. `0024` Schema、Repository、并发和迁移测试；
2. Recorder、版本化事件契约、读取模型和单元测试；
3. API/Agent 接入、确认关联、fail-open 和行为等价测试；
4. 完整门禁、独立复审与发布报告。

所有提交遵循仓库格式，例如：

```text
feat: AI add durable agent run journal
```

## 15. 后续演进

该项目完成后，再分别设计并实施：

1. Tool Execution Pipeline：统一结构化 ToolRequest/ToolOutcome、capability 与 approval；
2. Write Operation Ledger：把写入意图、审批、执行与结果形成独立账本；
3. Context Projector：只向模型暴露任务所需的上下文和工具表面；
4. Proposal/Attempt 标准化；
5. 最后才评估后台队列或多 Agent 编排。

Durable Journal 只提供这些项目需要的稳定运行身份与因果观察，不提前承担它们的职责。
