# OfferPilot AI 对话助手 — 设计文档

- 日期：2026-06-29
- 状态：已通过头脑风暴评审，待实现

## 1. 背景与目标

OfferPilot 目前的 AI 能力是「一问一答」式的固定功能（JD 分析、简历匹配、面试复盘笔记），AI 调用链路为 **前端 → Go 后端 `/api/*` → AI 厂商**，API key 存于后端 `~/.offerpilot/config.json`。

目标：新增一个**通用 AI 对话助手**，让用户能直接和 AI 聊天，且 AI 能感知并操作用户在 OfferPilot 里积累的求职数据（投递记录、JD 分析、简历、面试笔记）。

### 关键决策（来自头脑风暴）

1. **部署形态**：单用户自托管（与现状一致），key 继续放后端，浏览器不直连 AI 厂商。
2. **智能程度**：求职上下文感知 —— AI 能看到并使用用户的求职数据。
3. **数据接入方式**：**tool calling（function calling）**，AI 自主决定调用哪些工具获取/修改数据。
4. **权限**：读 + 写，**写操作默认需用户确认**；提供全局「免确认」开关（可配置）。
5. **响应方式**：先做**非流式**（一次性返回），流式输出留作第二期。
6. **历史持久化**：对话**持久化到后端 SQLite**，支持多会话与历史回看。
7. **实现路线**：统一工具抽象 + OpenAI / Anthropic 双协议适配器；不支持 tool calling 的模型自动降级为「摘要注入」只读模式。

## 2. 总体架构

沿用现有链路，新增五处改动：

| 层 | 改动 |
|---|---|
| `internal/ai` | 工具注册表 + 双协议适配器 + agentic 对话循环 |
| `internal/db` | `conversations` / `messages` 两张表 + CRUD |
| `internal/api` | `/api/chat` 系列接口 + `/api/settings` |
| `internal/config` | 新增 `chat_auto_approve_writes` 开关 |
| `web/src` | ChatPanel 对话界面 + 服务/类型 |

## 3. AI 层（核心）

### 3.1 工具定义（协议无关）

```go
type Tool struct {
    Name        string
    Description string
    Schema      json.RawMessage // JSON Schema，描述参数
    Write       bool            // 是否为写操作（影响确认流程）
    Handler     func(ctx context.Context, args json.RawMessage) (string, error)
}
```

Handler 在构造工具注册表时闭包持有 `*db.Database`，因此能直接查询/写入数据库。

**初始工具集：**

只读：
- `list_applications` — 列出投递记录（可按状态过滤）
- `get_application` — 取单条投递详情
- `list_jd_analyses` — 列出 JD 分析（可按 application_id 过滤）
- `get_jd_analysis` — 取单条 JD 分析
- `list_resumes` — 列出简历
- `get_resume` — 取单份简历内容
- `list_notes` — 列出面试复盘笔记（可按 application_id 过滤）

写（`Write: true`）：
- `create_application` — 新建投递
- `update_application_status` — 修改投递状态
- `add_note` — 追加一条面试复盘笔记

工具集刻意保持小，后续按需扩展。

### 3.2 对话循环 `ChatWithTools`

```
输入：messages（历史 + 当前）、tools、opts（autoApproveWrites、maxIterations）
循环（上限默认 8 轮）：
  1. 经协议适配器把 messages + 工具 schema 发给模型
  2. 若模型返回纯文本 → 即最终答案，返回
  3. 若模型要求调用工具：
     a. 只读工具 → 执行 → 把结果作为 tool 消息回灌 → 继续循环
     b. 写工具：
        - 若 autoApproveWrites = false → 中断循环，持久化含 tool_call 的
          助手消息，返回「待确认动作」给上层（见 §5 确认流程）
        - 若 autoApproveWrites = true → 直接执行 → 回灌结果 → 继续循环
  4. 超过循环上限 → 返回已生成内容 + 超限提示
```

消息类型需比现有 `Chat()` 更丰富：role ∈ {system, user, assistant, tool}，assistant 消息可携带 tool_calls，tool 消息携带 tool_call_id 与结果。

### 3.3 双协议适配器

- `adapter_openai.go`：内部格式 ↔ OpenAI `tools` / `tool_calls` / `role:"tool"`。
- `adapter_anthropic.go`：内部格式 ↔ Anthropic `tools` / `tool_use` / `tool_result`。
- 协议选择沿用现有 `Client.anthropic`（base_url 含 "anthropic"）。

**降级策略**：当检测到模型不支持 tool calling（请求报错指示工具不支持，或配置中将模型标记为无工具）时，自动切换到「摘要注入」无工具模式 —— 后端把用户数据整理成轻量摘要塞进 system prompt，聊天仍可用（只读、无主动查询/写入），并向用户提示「当前模型不支持工具调用，已切换为只读摘要模式」。

## 4. 数据模型（SQLite）

```sql
CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,          -- 取首条用户消息截断，默认 "新对话"
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,     -- user / assistant / tool
    content         TEXT,              -- 文本内容
    tool_calls      TEXT,              -- JSON，assistant 发起的工具调用，可空
    tool_call_id    TEXT,             -- tool 结果对应的调用 id，可空
    created_at      DATETIME NOT NULL
);
```

新增 `internal/db/chat.go`：创建会话、追加消息、列出会话、取会话消息、删除会话。

## 5. 写操作确认流程（中断—持久化—恢复）

非流式单次 HTTP 请求无法阻塞等待用户点击，因此采用中断后恢复：

```
用户: "把字节那条标记为已 offer，并总结我现在的进度"
1. POST /api/chat → 存用户消息，启动循环
2. AI 调 list_applications(只读) → 执行 → 继续
3. AI 调 update_application_status(写，未开免确认)
   → 后端中断循环，把含 tool_call 的助手消息存库，
     返回 {type:"confirmation_required",
           pending_action:{ tool, args, human_readable:"将『字节-后端』状态改为 已 offer" }}
4. 前端展示确认卡片 [确认] [取消]
5. 用户点确认 → POST /api/chat/confirm {conversation_id, approved:true}
6. 后端执行写操作，把结果作为 tool 消息回灌，从库读出消息恢复循环
   （若 approved:false，则回灌「用户取消了该操作」让模型继续）
7. AI 生成总结文本 → 存库 → 返回前端渲染
```

由于消息本就持久化，「恢复」即从库读出消息接着跑循环。

## 6. API 接口

- `POST /api/chat` — body `{conversation_id?, message}`
  - 无 conversation_id 则新建会话；持久化用户消息；运行循环
  - 返回助手回复 `{conversation_id, message}` **或** `{type:"confirmation_required", pending_action}`
- `POST /api/chat/confirm` — body `{conversation_id, approved}`
  - 执行/跳过待确认写操作，恢复循环，返回最终回复
- `GET /api/chat/conversations` — 会话列表
- `GET /api/chat/conversations/{id}` — 会话消息历史
- `DELETE /api/chat/conversations/{id}` — 删除会话
- `GET /api/settings` / `PUT /api/settings` — 读/改聊天相关设置（`chat_auto_approve_writes`）；**绝不返回或接收 API key**

路由通过 `registerChatRoutes` / `registerSettingsRoutes` 注册到 `internal/api/router.go`。

## 7. 配置

`internal/config/config.go` 的 `Config` 新增字段：

```go
ChatAutoApproveWrites bool `json:"chat_auto_approve_writes"` // 默认 false
```

可通过 `oc config` CLI 设置，也可通过前端设置开关（`PUT /api/settings`）修改。

## 8. 前端

- `web/src/types/chat.ts` — 类型定义
- `web/src/services/chat.ts` — API 调用封装
- `web/src/components/ChatPanel/` — 对话界面：
  - 左侧会话列表（新建 / 切换 / 删除）
  - 右侧消息流（助手回复走 markdown 渲染）
  - 输入框（回车发送）
  - 写操作确认卡片（[确认] [取消]）
  - 工具调用进行中提示（如「🔧 正在查询投递记录…」）
  - 免确认开关（调 `/api/settings`）
- 入口：App 顶部新增「AI 助手」按钮，抽屉式打开 ChatPanel

## 9. 错误处理与边界

- **未配置 key**：沿用 `ErrNotConfigured`，前端引导用户去设置页填 key。
- **模型不支持工具**：适配器检测后降级为只读摘要模式，并提示用户。
- **工具执行报错**：把错误文本作为 tool 结果回灌，让模型自行说明，而非直接中断。
- **循环超上限**（默认 8 轮）：返回已有内容 + 超限提示，避免死循环。
- **上下文超长**：截断最旧消息，保留 system prompt 与近期消息。

## 10. 测试

- Go（重点）：
  - 工具 Handler 单测（临时/内存 SQLite）
  - 适配器翻译 golden 测试（OpenAI / Anthropic 请求构造 & 响应解析）
  - 用 mock AI client 测对话循环、确认中断/恢复、循环上限
- 前端（轻量）：确认卡片组件测试

## 11. 范围与 YAGNI

明确**不在本期**：
- 流式输出（第二期体验优化）
- 多用户 / 浏览器直连 AI 厂商
- 按工具粒度的细粒度权限（仅做全局免确认开关）
- 大规模工具集（先保持上述小工具集）
```