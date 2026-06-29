# OfferPilot AI 对话助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 OfferPilot 增加一个能感知并操作用户求职数据的通用 AI 对话助手，前端聊天、后端走 tool calling，支持写操作确认与多会话历史持久化。

**Architecture:** 沿用现有链路 前端 → Go 后端 `/api/chat` → AI 厂商（key 仍只在后端）。AI 层用协议无关的工具注册表 + agentic 对话循环，OpenAI / Anthropic 双适配器，模型不支持工具时降级为只读摘要模式。对话与消息持久化到 SQLite。

**Tech Stack:** Go (chi, modernc.org/sqlite, cobra) + React 18 (Ant Design, React Query, axios, 新增 react-markdown)。

**对应设计文档:** `docs/superpowers/specs/2026-06-29-ai-chat-assistant-design.md`

---

## 关键约定（实现者必读）

1. **一次一个工具**：系统提示词要求模型每轮最多调用一个工具；适配器解析时若模型返回多个 tool call，只取第一个。这样对话循环与「写操作中断—恢复」逻辑保持简单，且协议层不会出现「部分 tool_call 未应答」的非法状态。
2. **system 提示词不入库**：每次构造消息时在最前面拼一条 system 消息；数据库只存 user / assistant / tool 三种角色。
3. **降级**：当 `Complete` 因模型不支持工具而失败（HTTP 4xx 且响应体含工具相关错误标记）时，返回 `ErrToolsUnsupported`，handler 改走 `RunSummaryFallback`（注入数据摘要的单轮对话）。
4. **前端测试**：现有 `web/` 无测试框架，本计划遵循其现状，前端以「构建 + 手动验证」收尾，不引入 vitest（避免范围蔓延）。Go 侧严格 TDD。

---

## 文件结构

**新建（Go）**
- `internal/db/chat.go` — conversations / messages 表的迁移调用点说明 + CRUD
- `internal/db/chat_test.go`
- `internal/ai/types.go` — 协议无关的 Message / Role / ToolCall / Assistant 类型
- `internal/ai/tools.go` — Tool 定义 + Registry + 各工具 Handler
- `internal/ai/tools_test.go`
- `internal/ai/agent.go` — RunTurn / ResumeAfterConfirm 对话循环 + ChatModel 接口 + 系统提示词
- `internal/ai/agent_test.go`
- `internal/ai/complete_openai.go` — Client.completeOpenAI 适配器
- `internal/ai/complete_anthropic.go` — Client.completeAnthropic 适配器
- `internal/ai/complete_test.go`
- `internal/ai/summary.go` — RunSummaryFallback 降级模式 + 数据摘要
- `internal/ai/summary_test.go`
- `internal/api/chat.go` — /api/chat、/api/chat/confirm、会话 CRUD
- `internal/api/settings.go` — GET/PUT /api/settings
- `internal/api/chat_test.go`

**修改（Go）**
- `internal/db/db.go` — migrate() 增加两张表
- `internal/ai/client.go` — 增加 `Complete` 方法分发 + `ErrToolsUnsupported`
- `internal/config/config.go` — 增加 `ChatAutoApproveWrites` 字段
- `internal/api/router.go` — 注册 chat / settings 路由
- `internal/cli/root.go` — config 命令增加 `--auto-approve` 开关

**新建/修改（前端）**
- `web/src/types/chat.ts`
- `web/src/services/chat.ts`
- `web/src/components/ChatPanel/index.tsx`
- `web/src/components/ChatPanel/ConfirmCard.tsx`
- `web/src/components/ChatPanel/ChatPanel.module.css`
- `web/src/App.tsx` — 顶部增加「AI 助手」入口
- `web/package.json` — 增加 `react-markdown`

---

## Task 1: 数据库 conversations / messages 表 + CRUD

**Files:**
- Modify: `internal/db/db.go`（migrate 增加两张表）
- Create: `internal/db/chat.go`
- Test: `internal/db/chat_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/db/chat_test.go`:

```go
package db

import (
	"path/filepath"
	"testing"
)

func newTestDB(t *testing.T) *Database {
	t.Helper()
	dbPath := filepath.Join(t.TempDir(), "test.db")
	d, err := Init(dbPath)
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestConversationAndMessageCRUD(t *testing.T) {
	d := newTestDB(t)

	conv, err := d.CreateConversation("找工作进度")
	if err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	if conv.ID == 0 {
		t.Fatal("expected non-zero conversation id")
	}

	if err := d.AppendMessage(&ChatMessage{
		ConversationID: conv.ID,
		Role:           "user",
		Content:        "你好",
	}); err != nil {
		t.Fatalf("append user: %v", err)
	}
	if err := d.AppendMessage(&ChatMessage{
		ConversationID: conv.ID,
		Role:           "assistant",
		Content:        "",
		ToolCalls:      `[{"id":"c1","name":"list_applications","args":{}}]`,
	}); err != nil {
		t.Fatalf("append assistant: %v", err)
	}

	msgs, err := d.ListMessages(conv.ID)
	if err != nil {
		t.Fatalf("list messages: %v", err)
	}
	if len(msgs) != 2 {
		t.Fatalf("want 2 messages, got %d", len(msgs))
	}
	if msgs[0].Role != "user" || msgs[1].ToolCalls == "" {
		t.Fatalf("unexpected message ordering/content: %+v", msgs)
	}

	convs, err := d.ListConversations()
	if err != nil {
		t.Fatalf("list conversations: %v", err)
	}
	if len(convs) != 1 {
		t.Fatalf("want 1 conversation, got %d", len(convs))
	}

	if err := d.DeleteConversation(conv.ID); err != nil {
		t.Fatalf("delete conversation: %v", err)
	}
	after, _ := d.ListMessages(conv.ID)
	if len(after) != 0 {
		t.Fatalf("expected cascade delete of messages, got %d", len(after))
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/db/ -run TestConversationAndMessageCRUD -v`
Expected: 编译失败 / undefined: CreateConversation 等。

- [ ] **Step 3: 增加迁移**

In `internal/db/db.go`, 在 `migrate()` 的 `migrations := []string{...}` 列表中，`idx_*` 索引语句之前，追加两张表：

```go
		`CREATE TABLE IF NOT EXISTS conversations (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			title TEXT NOT NULL DEFAULT '新对话',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS chat_messages (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			conversation_id INTEGER NOT NULL,
			role TEXT NOT NULL,
			content TEXT DEFAULT '',
			tool_calls TEXT DEFAULT '',
			tool_call_id TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
		)`,
		`CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id)`,
```

注意：sqlite 默认不启用外键级联，删除会话时需手动删消息（见 DeleteConversation）。

- [ ] **Step 4: 实现 CRUD**

Create `internal/db/chat.go`:

```go
package db

import "time"

// Conversation is a chat session with the AI assistant.
type Conversation struct {
	ID        int64     `json:"id"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ChatMessage is a single turn in a conversation. ToolCalls holds a JSON array
// (assistant turns that request tools); ToolCallID links a tool-result turn back
// to the call that produced it. Both are empty strings when unused.
type ChatMessage struct {
	ID             int64     `json:"id"`
	ConversationID int64     `json:"conversation_id"`
	Role           string    `json:"role"` // user | assistant | tool
	Content        string    `json:"content"`
	ToolCalls      string    `json:"tool_calls,omitempty"`
	ToolCallID     string    `json:"tool_call_id,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

// CreateConversation inserts a new conversation and returns it with its ID set.
func (db *Database) CreateConversation(title string) (*Conversation, error) {
	if title == "" {
		title = "新对话"
	}
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)`,
		title, now, now,
	)
	if err != nil {
		return nil, err
	}
	id, _ := res.LastInsertId()
	return &Conversation{ID: id, Title: title, CreatedAt: now, UpdatedAt: now}, nil
}

// ListConversations returns all conversations, most recently updated first.
func (db *Database) ListConversations() ([]Conversation, error) {
	rows, err := db.conn.Query(
		`SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Conversation
	for rows.Next() {
		var c Conversation
		if err := rows.Scan(&c.ID, &c.Title, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

// AppendMessage stores one message and bumps the conversation's updated_at.
func (db *Database) AppendMessage(m *ChatMessage) error {
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO chat_messages (conversation_id, role, content, tool_calls, tool_call_id, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		m.ConversationID, m.Role, m.Content, m.ToolCalls, m.ToolCallID, now,
	)
	if err != nil {
		return err
	}
	m.ID, _ = res.LastInsertId()
	m.CreatedAt = now
	_, _ = db.conn.Exec(`UPDATE conversations SET updated_at = ? WHERE id = ?`, now, m.ConversationID)
	return nil
}

// ListMessages returns all messages in a conversation, oldest first.
func (db *Database) ListMessages(convID int64) ([]ChatMessage, error) {
	rows, err := db.conn.Query(
		`SELECT id, conversation_id, role, content, tool_calls, tool_call_id, created_at
		 FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC`, convID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ChatMessage
	for rows.Next() {
		var m ChatMessage
		if err := rows.Scan(&m.ID, &m.ConversationID, &m.Role, &m.Content, &m.ToolCalls, &m.ToolCallID, &m.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, nil
}

// DeleteConversation removes a conversation and its messages.
func (db *Database) DeleteConversation(id int64) error {
	if _, err := db.conn.Exec(`DELETE FROM chat_messages WHERE conversation_id = ?`, id); err != nil {
		return err
	}
	_, err := db.conn.Exec(`DELETE FROM conversations WHERE id = ?`, id)
	return err
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `go test ./internal/db/ -run TestConversationAndMessageCRUD -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add internal/db/db.go internal/db/chat.go internal/db/chat_test.go
git commit -m "feat(db): conversations and chat_messages tables with CRUD"
```

---

## Task 2: AI 协议无关类型 + 工具注册表

**Files:**
- Create: `internal/ai/types.go`
- Create: `internal/ai/tools.go`
- Test: `internal/ai/tools_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/ai/tools_test.go`:

```go
package ai

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func newToolDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/t.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestRegistryListAndReadTool(t *testing.T) {
	d := newToolDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})

	reg := NewRegistry(d)
	if len(reg.List()) == 0 {
		t.Fatal("expected tools registered")
	}

	out, err := reg.Execute(context.Background(), "list_applications", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if !strings.Contains(out, "字节") {
		t.Fatalf("expected company in output, got %s", out)
	}
}

func TestRegistryWriteToolCreatesApplication(t *testing.T) {
	d := newToolDB(t)
	reg := NewRegistry(d)

	_, err := reg.Execute(context.Background(), "create_application",
		json.RawMessage(`{"company_name":"腾讯","position_name":"前端"}`))
	if err != nil {
		t.Fatalf("execute create: %v", err)
	}
	apps, _ := d.ListApplications("")
	if len(apps) != 1 || apps[0].CompanyName != "腾讯" {
		t.Fatalf("expected created application, got %+v", apps)
	}

	tool, ok := reg.Get("create_application")
	if !ok || !tool.Write {
		t.Fatal("create_application should be a write tool")
	}
}

func TestUnknownToolErrors(t *testing.T) {
	reg := NewRegistry(newToolDB(t))
	if _, err := reg.Execute(context.Background(), "does_not_exist", json.RawMessage(`{}`)); err == nil {
		t.Fatal("expected error for unknown tool")
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/ai/ -run TestRegistry -v`
Expected: 编译失败（undefined NewRegistry 等）。

- [ ] **Step 3: 实现协议无关类型**

Create `internal/ai/types.go`:

```go
package ai

import "encoding/json"

// Role enumerates message roles in a tool-calling conversation.
type Role string

const (
	RoleSystem    Role = "system"
	RoleUser      Role = "user"
	RoleAssistant Role = "assistant"
	RoleTool      Role = "tool"
)

// ToolCall is a single tool invocation requested by the model.
// Args is the raw JSON arguments object.
type ToolCall struct {
	ID   string          `json:"id"`
	Name string          `json:"name"`
	Args json.RawMessage `json:"args"`
}

// Message is one turn in a conversation, protocol-agnostic.
// ToolCalls is set on assistant turns that request tools;
// ToolCallID is set on tool-result turns.
type Message struct {
	Role       Role       `json:"role"`
	Content    string     `json:"content"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

// Assistant is one assistant turn returned by a model: either free text,
// or one-or-more tool calls (we only ever act on the first — see plan note).
type Assistant struct {
	Content   string
	ToolCalls []ToolCall
}
```

- [ ] **Step 4: 实现工具注册表与 Handler**

Create `internal/ai/tools.go`:

```go
package ai

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/offercontext/offerpilot/internal/db"
)

// Tool is a protocol-agnostic capability the model can invoke.
// Schema is a JSON Schema object describing Handler's argument shape.
// Write marks tools that mutate data (gated by the confirmation flow).
// Describe renders a human-readable confirmation string for write tools.
type Tool struct {
	Name        string
	Description string
	Schema      json.RawMessage
	Write       bool
	Handler     func(ctx context.Context, args json.RawMessage) (string, error)
	Describe    func(args json.RawMessage) string
}

// Registry holds the available tools, built against a database handle.
type Registry struct {
	tools map[string]Tool
	order []string
}

// List returns tools in registration order.
func (r *Registry) List() []Tool {
	out := make([]Tool, 0, len(r.order))
	for _, name := range r.order {
		out = append(out, r.tools[name])
	}
	return out
}

// Get returns a tool by name.
func (r *Registry) Get(name string) (Tool, bool) {
	t, ok := r.tools[name]
	return t, ok
}

// Execute runs a tool's handler. Returns an error for unknown tools.
func (r *Registry) Execute(ctx context.Context, name string, args json.RawMessage) (string, error) {
	t, ok := r.tools[name]
	if !ok {
		return "", fmt.Errorf("unknown tool %q", name)
	}
	return t.Handler(ctx, args)
}

func (r *Registry) add(t Tool) {
	r.tools[t.Name] = t
	r.order = append(r.order, t.Name)
}

// jsonResult marshals v to a compact JSON string for feeding back to the model.
func jsonResult(v interface{}) (string, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// NewRegistry builds the tool set bound to the given database.
func NewRegistry(database *db.Database) *Registry {
	r := &Registry{tools: map[string]Tool{}}

	// ---- read tools ----
	r.add(Tool{
		Name:        "list_applications",
		Description: "列出求职投递记录，可按状态过滤。状态取值：applied/assessment/written_test/interview/offer/eliminated/rejected。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"status":{"type":"string","description":"可选状态过滤"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ Status string `json:"status"` }
			_ = json.Unmarshal(args, &p)
			apps, err := database.ListApplications(p.Status)
			if err != nil {
				return "", err
			}
			return jsonResult(apps)
		},
	})
	r.add(Tool{
		Name:        "get_application",
		Description: "按 ID 获取单条投递记录的详情。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ID int64 `json:"id"` }
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			app, err := database.GetApplication(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "list_jd_analyses",
		Description: "列出 JD 分析结果，可按 application_id 过滤（传 0 或省略列出全部）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ApplicationID int64 `json:"application_id"` }
			_ = json.Unmarshal(args, &p)
			items, err := database.ListJDAnalyses(p.ApplicationID)
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_jd_analysis",
		Description: "按 ID 获取单条 JD 分析详情。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ID int64 `json:"id"` }
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			a, err := database.GetJDAnalysis(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(a)
		},
	})
	r.add(Tool{
		Name:        "list_resumes",
		Description: "列出已保存的简历（含简历文本）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			items, err := database.ListResumes()
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_resume",
		Description: "按 ID 获取单份简历的完整文本。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ID int64 `json:"id"` }
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			res, err := database.GetResume(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(res)
		},
	})
	r.add(Tool{
		Name:        "list_notes",
		Description: "列出面试复盘笔记，可按 application_id 过滤（传 0 或省略列出全部）。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ApplicationID int64 `json:"application_id"` }
			_ = json.Unmarshal(args, &p)
			items, err := database.ListInterviewNotes(p.ApplicationID)
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})

	// ---- write tools ----
	r.add(Tool{
		Name:        "create_application",
		Description: "新建一条投递记录。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"company_name":{"type":"string"},"position_name":{"type":"string"},"job_url":{"type":"string"},"status":{"type":"string"}},"required":["company_name","position_name"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				Company  string `json:"company_name"`
				Position string `json:"position_name"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("新建投递：%s - %s", p.Company, p.Position)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Company  string `json:"company_name"`
				Position string `json:"position_name"`
				JobURL   string `json:"job_url"`
				Status   string `json:"status"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if p.Status == "" {
				p.Status = "applied"
			}
			app := &db.Application{
				CompanyName: p.Company, PositionName: p.Position,
				JobURL: p.JobURL, Status: p.Status, Source: "ai",
			}
			if err := database.CreateApplication(app); err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "update_application_status",
		Description: "修改某条投递的状态。状态取值：applied/assessment/written_test/interview/offer/eliminated/rejected。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"status":{"type":"string"}},"required":["id","status"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID     int64  `json:"id"`
				Status string `json:"status"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("将投递 #%d 的状态改为 %s", p.ID, p.Status)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID     int64  `json:"id"`
				Status string `json:"status"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			app, err := database.GetApplication(p.ID)
			if err != nil {
				return "", err
			}
			app.Status = p.Status
			if err := database.UpdateApplication(app); err != nil {
				return "", err
			}
			return jsonResult(app)
		},
	})
	r.add(Tool{
		Name:        "add_note",
		Description: "为某次面试追加一条复盘笔记。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"application_id":{"type":"integer"}},"required":["company","position"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				Company  string `json:"company"`
				Position string `json:"position"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("新增面试复盘笔记：%s - %s", p.Company, p.Position)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Company        string `json:"company"`
				Position       string `json:"position"`
				Round          string `json:"round"`
				Questions      string `json:"questions"`
				SelfReflection string `json:"self_reflection"`
				ApplicationID  *int64 `json:"application_id"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			note := &db.InterviewNote{
				ApplicationID: p.ApplicationID, Company: p.Company, Position: p.Position,
				Round: p.Round, Questions: p.Questions, SelfReflection: p.SelfReflection,
			}
			if err := database.CreateInterviewNote(note); err != nil {
				return "", err
			}
			return jsonResult(note)
		},
	})

	return r
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `go test ./internal/ai/ -run TestRegistry -v && go test ./internal/ai/ -run TestUnknownTool -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add internal/ai/types.go internal/ai/tools.go internal/ai/tools_test.go
git commit -m "feat(ai): protocol-agnostic message types and tool registry"
```

---

## Task 3: 对话循环 RunTurn / ResumeAfterConfirm

**Files:**
- Create: `internal/ai/agent.go`
- Test: `internal/ai/agent_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/ai/agent_test.go`:

```go
package ai

import (
	"context"
	"encoding/json"
	"errors"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

// scriptedModel returns pre-scripted assistant turns in order.
type scriptedModel struct {
	turns []Assistant
	i     int
}

func (m *scriptedModel) Complete(_ context.Context, _ []Message, _ []Tool) (*Assistant, error) {
	if m.i >= len(m.turns) {
		return nil, errors.New("scriptedModel: no more turns")
	}
	a := m.turns[m.i]
	m.i++
	return &a, nil
}

func agentDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/a.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestRunTurnReadThenText(t *testing.T) {
	d := agentDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})
	reg := NewRegistry(d)
	model := &scriptedModel{turns: []Assistant{
		{ToolCalls: []ToolCall{{ID: "c1", Name: "list_applications", Args: json.RawMessage(`{}`)}}},
		{Content: "你目前有 1 条投递。"},
	}}

	added, reply, pending, err := RunTurn(context.Background(), model, reg,
		[]Message{{Role: RoleUser, Content: "我有几条投递？"}}, false, 8)
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	if pending != nil {
		t.Fatal("did not expect pending action")
	}
	if reply != "你目前有 1 条投递。" {
		t.Fatalf("unexpected reply: %q", reply)
	}
	// assistant(toolcall), tool(result), assistant(text)
	if len(added) != 3 {
		t.Fatalf("want 3 added messages, got %d", len(added))
	}
}

func TestRunTurnWritePauses(t *testing.T) {
	d := agentDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})
	reg := NewRegistry(d)
	model := &scriptedModel{turns: []Assistant{
		{ToolCalls: []ToolCall{{ID: "w1", Name: "update_application_status", Args: json.RawMessage(`{"id":1,"status":"offer"}`)}}},
	}}

	added, reply, pending, err := RunTurn(context.Background(), model, reg,
		[]Message{{Role: RoleUser, Content: "把字节标记 offer"}}, false, 8)
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	if pending == nil {
		t.Fatal("expected pending action for write tool")
	}
	if reply != "" {
		t.Fatalf("expected empty reply on pause, got %q", reply)
	}
	if pending.ToolName != "update_application_status" || pending.Human == "" {
		t.Fatalf("unexpected pending: %+v", pending)
	}
	// only the assistant(toolcall) message added; write NOT executed yet
	if len(added) != 1 {
		t.Fatalf("want 1 added message, got %d", len(added))
	}
	app, _ := d.GetApplication(1)
	if app.Status == "offer" {
		t.Fatal("write should not have executed before confirmation")
	}
}

func TestRunTurnWriteAutoApprove(t *testing.T) {
	d := agentDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})
	reg := NewRegistry(d)
	model := &scriptedModel{turns: []Assistant{
		{ToolCalls: []ToolCall{{ID: "w1", Name: "update_application_status", Args: json.RawMessage(`{"id":1,"status":"offer"}`)}}},
		{Content: "已更新。"},
	}}

	_, reply, pending, err := RunTurn(context.Background(), model, reg,
		[]Message{{Role: RoleUser, Content: "把字节标记 offer"}}, true, 8)
	if err != nil {
		t.Fatalf("run: %v", err)
	}
	if pending != nil {
		t.Fatal("auto-approve should not pause")
	}
	if reply != "已更新。" {
		t.Fatalf("unexpected reply: %q", reply)
	}
	app, _ := d.GetApplication(1)
	if app.Status != "offer" {
		t.Fatalf("expected status offer, got %s", app.Status)
	}
}

func TestResumeAfterConfirmApproved(t *testing.T) {
	d := agentDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})
	reg := NewRegistry(d)
	pending := &PendingAction{ToolCallID: "w1", ToolName: "update_application_status", Args: json.RawMessage(`{"id":1,"status":"offer"}`)}
	model := &scriptedModel{turns: []Assistant{{Content: "已标记为 offer。"}}}
	history := []Message{
		{Role: RoleUser, Content: "把字节标记 offer"},
		{Role: RoleAssistant, ToolCalls: []ToolCall{{ID: "w1", Name: "update_application_status", Args: pending.Args}}},
	}

	added, reply, newPending, err := ResumeAfterConfirm(context.Background(), model, reg, history, pending, true, false, 8)
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if newPending != nil {
		t.Fatal("did not expect a second pending action")
	}
	if reply != "已标记为 offer。" {
		t.Fatalf("unexpected reply: %q", reply)
	}
	// tool(result) + assistant(text)
	if len(added) != 2 || added[0].Role != RoleTool {
		t.Fatalf("unexpected added messages: %+v", added)
	}
	app, _ := d.GetApplication(1)
	if app.Status != "offer" {
		t.Fatalf("expected status offer, got %s", app.Status)
	}
}

func TestRunTurnMaxIterations(t *testing.T) {
	d := agentDB(t)
	reg := NewRegistry(d)
	// model keeps requesting a read tool forever
	turns := make([]Assistant, 10)
	for i := range turns {
		turns[i] = Assistant{ToolCalls: []ToolCall{{ID: "c", Name: "list_applications", Args: json.RawMessage(`{}`)}}}
	}
	model := &scriptedModel{turns: turns}
	_, _, _, err := RunTurn(context.Background(), model, reg,
		[]Message{{Role: RoleUser, Content: "loop"}}, false, 3)
	if !errors.Is(err, ErrMaxIterations) {
		t.Fatalf("expected ErrMaxIterations, got %v", err)
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/ai/ -run "TestRunTurn|TestResumeAfterConfirm" -v`
Expected: 编译失败（undefined RunTurn 等）。

- [ ] **Step 3: 实现 agent.go**

Create `internal/ai/agent.go`:

```go
package ai

import (
	"context"
	"errors"
	"fmt"
)

// ErrMaxIterations is returned when the tool-calling loop exceeds its limit.
var ErrMaxIterations = errors.New("AI 工具调用超过最大轮次")

// DefaultMaxIterations bounds the tool-calling loop.
const DefaultMaxIterations = 8

// ChatSystemPrompt instructs the model on its role and the one-tool-per-turn rule.
const ChatSystemPrompt = "你是 OfferPilot 的求职助手。你可以调用工具来查询或修改用户的求职数据" +
	"（投递记录、JD 分析、简历、面试复盘笔记）。规则：" +
	"1. 每轮最多调用一个工具，等到结果返回后再决定下一步。" +
	"2. 需要数据时优先调用工具获取真实数据，不要凭空编造。" +
	"3. 所有回复使用简体中文，简洁清晰。" +
	"4. 修改类操作（新建/改状态/加笔记）调用对应写工具即可，系统会在必要时向用户确认。"

// ChatModel is the minimal interface the loop needs from an AI client.
// *Client implements it; tests provide mocks.
type ChatModel interface {
	Complete(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error)
}

// PendingAction describes a write tool call awaiting user confirmation.
type PendingAction struct {
	ToolCallID string          `json:"tool_call_id"`
	ToolName   string          `json:"tool_name"`
	Args       json.RawMessage `json:"args"`
	Human      string          `json:"human"`
}

// RunTurn drives the tool-calling loop until the model returns text, requests a
// write while autoApprove is off (pausing), or hits maxIter.
//
// messages must already include any system prompt and full prior history plus
// the new user message. The returned `added` slice contains only the new
// assistant/tool messages produced this turn (caller persists them).
func RunTurn(ctx context.Context, model ChatModel, reg *Registry, messages []Message, autoApprove bool, maxIter int) (added []Message, reply string, pending *PendingAction, err error) {
	if maxIter <= 0 {
		maxIter = DefaultMaxIterations
	}
	work := append([]Message{}, messages...)

	for i := 0; i < maxIter; i++ {
		asst, err := model.Complete(ctx, work, reg.List())
		if err != nil {
			return added, "", nil, err
		}
		if len(asst.ToolCalls) == 0 {
			m := Message{Role: RoleAssistant, Content: asst.Content}
			added = append(added, m)
			return added, asst.Content, nil, nil
		}

		// One tool per turn: act only on the first.
		tc := asst.ToolCalls[0]
		asstMsg := Message{Role: RoleAssistant, Content: asst.Content, ToolCalls: []ToolCall{tc}}
		added = append(added, asstMsg)
		work = append(work, asstMsg)

		tool, ok := reg.Get(tc.Name)
		if !ok {
			res := fmt.Sprintf("错误：未知工具 %q", tc.Name)
			tm := Message{Role: RoleTool, Content: res, ToolCallID: tc.ID}
			added = append(added, tm)
			work = append(work, tm)
			continue
		}

		if tool.Write && !autoApprove {
			human := tc.Name
			if tool.Describe != nil {
				human = tool.Describe(tc.Args)
			}
			pending = &PendingAction{ToolCallID: tc.ID, ToolName: tc.Name, Args: tc.Args, Human: human}
			return added, "", pending, nil
		}

		out, execErr := reg.Execute(ctx, tc.Name, tc.Args)
		if execErr != nil {
			out = "错误：" + execErr.Error()
		}
		tm := Message{Role: RoleTool, Content: out, ToolCallID: tc.ID}
		added = append(added, tm)
		work = append(work, tm)
	}
	return added, "", nil, ErrMaxIterations
}

// ResumeAfterConfirm executes (or rejects) a paused write, appends its tool
// result, then continues the loop. `messages` is the full history including the
// paused assistant message that requested the write.
func ResumeAfterConfirm(ctx context.Context, model ChatModel, reg *Registry, messages []Message, pending *PendingAction, approved bool, autoApprove bool, maxIter int) (added []Message, reply string, newPending *PendingAction, err error) {
	var result string
	if approved {
		out, execErr := reg.Execute(ctx, pending.ToolName, pending.Args)
		if execErr != nil {
			result = "错误：" + execErr.Error()
		} else {
			result = out
		}
	} else {
		result = "用户拒绝了该操作，请勿执行，并询问用户下一步希望怎么做。"
	}

	tm := Message{Role: RoleTool, Content: result, ToolCallID: pending.ToolCallID}
	added = append(added, tm)

	full := append(append([]Message{}, messages...), tm)
	more, reply, newPending, err := RunTurn(ctx, model, reg, full, autoApprove, maxIter)
	added = append(added, more...)
	return added, reply, newPending, err
}
```

- [ ] **Step 4: 在 types.go 引入的 json 包给 agent.go 用**

`agent.go` 使用了 `json.RawMessage`，需在其 import 中加入 `"encoding/json"`。把 Step 3 文件顶部 import 改为：

```go
import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `go test ./internal/ai/ -run "TestRunTurn|TestResumeAfterConfirm" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add internal/ai/agent.go internal/ai/agent_test.go
git commit -m "feat(ai): tool-calling loop with write-confirmation pause/resume"
```

---

## Task 4: OpenAI 协议适配器 Complete

**Files:**
- Create: `internal/ai/complete_openai.go`
- Modify: `internal/ai/client.go`（增加 Complete 分发 + ErrToolsUnsupported）
- Test: `internal/ai/complete_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/ai/complete_test.go`:

```go
package ai

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/config"
)

func TestCompleteOpenAIParsesToolCall(t *testing.T) {
	var gotBody map[string]interface{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &gotBody)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"list_applications","arguments":"{\"status\":\"interview\"}"}}]}}]}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL, Model: "gpt-4o"})
	tools := []Tool{{Name: "list_applications", Description: "x", Schema: json.RawMessage(`{"type":"object"}`)}}
	msgs := []Message{{Role: RoleSystem, Content: "sys"}, {Role: RoleUser, Content: "hi"}}

	asst, err := c.Complete(context.Background(), msgs, tools)
	if err != nil {
		t.Fatalf("complete: %v", err)
	}
	if len(asst.ToolCalls) != 1 || asst.ToolCalls[0].Name != "list_applications" {
		t.Fatalf("unexpected tool calls: %+v", asst.ToolCalls)
	}
	if string(asst.ToolCalls[0].Args) != `{"status":"interview"}` {
		t.Fatalf("unexpected args: %s", asst.ToolCalls[0].Args)
	}
	// request must include tools array
	if gotBody["tools"] == nil {
		t.Fatal("request missing tools")
	}
}

func TestCompleteOpenAIParsesText(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"你好"}}]}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL, Model: "gpt-4o"})
	asst, err := c.Complete(context.Background(), []Message{{Role: RoleUser, Content: "hi"}}, nil)
	if err != nil {
		t.Fatalf("complete: %v", err)
	}
	if asst.Content != "你好" || len(asst.ToolCalls) != 0 {
		t.Fatalf("unexpected assistant: %+v", asst)
	}
}

func TestCompleteOpenAIToolsUnsupported(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":{"message":"this model does not support tools / function calling","type":"invalid_request_error"}}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL, Model: "local"})
	_, err := c.Complete(context.Background(),
		[]Message{{Role: RoleUser, Content: "hi"}},
		[]Tool{{Name: "x", Schema: json.RawMessage(`{}`)}})
	if err == nil || !strings.Contains(err.Error(), "tools") {
		// sanity; main assertion below
	}
	if !errorsIsToolsUnsupported(err) {
		t.Fatalf("expected ErrToolsUnsupported, got %v", err)
	}
}

func errorsIsToolsUnsupported(err error) bool {
	for err != nil {
		if err == ErrToolsUnsupported {
			return true
		}
		type unwrap interface{ Unwrap() error }
		u, ok := err.(unwrap)
		if !ok {
			return false
		}
		err = u.Unwrap()
	}
	return false
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/ai/ -run TestCompleteOpenAI -v`
Expected: 编译失败（undefined Complete / ErrToolsUnsupported）。

- [ ] **Step 3: 在 client.go 增加分发与哨兵错误**

In `internal/ai/client.go`，在 `ErrNotConfigured` 声明下方新增：

```go
// ErrToolsUnsupported signals the configured model rejected a tools request,
// so the caller should retry in no-tools (summary) mode.
var ErrToolsUnsupported = errors.New("model does not support tool calling")
```

并在 `Chat` 方法下方新增 Complete 分发：

```go
// Complete sends a multi-turn message list (with optional tools) and returns
// one assistant turn. It dispatches by protocol like Chat does.
func (c *Client) Complete(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	if c.anthropic {
		return c.completeAnthropic(ctx, messages, tools)
	}
	return c.completeOpenAI(ctx, messages, tools)
}

// isToolsUnsupportedBody heuristically detects "model can't do tools" errors.
func isToolsUnsupportedBody(body string) bool {
	b := strings.ToLower(body)
	hasTool := strings.Contains(b, "tool") || strings.Contains(b, "function")
	hasNeg := strings.Contains(b, "not support") || strings.Contains(b, "unsupported") ||
		strings.Contains(b, "no support") || strings.Contains(b, "not available") ||
		strings.Contains(b, "unknown") || strings.Contains(b, "invalid")
	return hasTool && hasNeg
}
```

（`errors` 与 `strings` 已在 client.go 的 import 中。）

- [ ] **Step 4: 实现 completeOpenAI**

Create `internal/ai/complete_openai.go`:

```go
package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type oaTool struct {
	Type     string `json:"type"`
	Function struct {
		Name        string          `json:"name"`
		Description string          `json:"description"`
		Parameters  json.RawMessage `json:"parameters"`
	} `json:"function"`
}

type oaToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"`
	} `json:"function"`
}

type oaMessage struct {
	Role       string       `json:"role"`
	Content    string       `json:"content"`
	ToolCalls  []oaToolCall `json:"tool_calls,omitempty"`
	ToolCallID string       `json:"tool_call_id,omitempty"`
}

type oaRequest struct {
	Model      string      `json:"model"`
	Messages   []oaMessage `json:"messages"`
	Tools      []oaTool    `json:"tools,omitempty"`
	ToolChoice string      `json:"tool_choice,omitempty"`
}

type oaResponse struct {
	Choices []struct {
		Message struct {
			Content   string       `json:"content"`
			ToolCalls []oaToolCall `json:"tool_calls"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func (c *Client) completeOpenAI(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	req := oaRequest{Model: c.model}
	for _, m := range messages {
		om := oaMessage{Role: string(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		for _, tc := range m.ToolCalls {
			var c oaToolCall
			c.ID = tc.ID
			c.Type = "function"
			c.Function.Name = tc.Name
			c.Function.Arguments = string(tc.Args)
			om.ToolCalls = append(om.ToolCalls, c)
		}
		req.Messages = append(req.Messages, om)
	}
	for _, t := range tools {
		var ot oaTool
		ot.Type = "function"
		ot.Function.Name = t.Name
		ot.Function.Description = t.Description
		ot.Function.Parameters = t.Schema
		req.Tools = append(req.Tools, ot)
	}
	if len(tools) > 0 {
		req.ToolChoice = "auto"
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("call AI API: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		if len(tools) > 0 && isToolsUnsupportedBody(string(raw)) {
			return nil, fmt.Errorf("%w: %s", ErrToolsUnsupported, truncate(string(raw), 200))
		}
		return nil, fmt.Errorf("AI API returned %d: %s", resp.StatusCode, truncate(string(raw), 200))
	}

	var or oaResponse
	if err := json.Unmarshal(raw, &or); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	if len(or.Choices) == 0 {
		return nil, fmt.Errorf("AI API returned no choices")
	}
	msg := or.Choices[0].Message
	asst := &Assistant{Content: msg.Content}
	for _, tc := range msg.ToolCalls {
		args := json.RawMessage(tc.Function.Arguments)
		if len(args) == 0 {
			args = json.RawMessage(`{}`)
		}
		asst.ToolCalls = append(asst.ToolCalls, ToolCall{ID: tc.ID, Name: tc.Function.Name, Args: args})
	}
	return asst, nil
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `go test ./internal/ai/ -run TestCompleteOpenAI -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add internal/ai/client.go internal/ai/complete_openai.go internal/ai/complete_test.go
git commit -m "feat(ai): OpenAI Complete adapter with tools and downgrade detection"
```

---

## Task 5: Anthropic 协议适配器 Complete

**Files:**
- Create: `internal/ai/complete_anthropic.go`
- Test: 追加到 `internal/ai/complete_test.go`

- [ ] **Step 1: 追加失败测试**

Append to `internal/ai/complete_test.go`:

```go
func TestCompleteAnthropicParsesToolUse(t *testing.T) {
	var gotBody map[string]interface{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &gotBody)
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"好的"},{"type":"tool_use","id":"toolu_1","name":"list_applications","input":{"status":"offer"}}],"stop_reason":"tool_use"}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL + "/anthropic", Model: "claude-3"})
	tools := []Tool{{Name: "list_applications", Description: "x", Schema: json.RawMessage(`{"type":"object"}`)}}
	asst, err := c.Complete(context.Background(),
		[]Message{{Role: RoleSystem, Content: "sys"}, {Role: RoleUser, Content: "hi"}}, tools)
	if err != nil {
		t.Fatalf("complete: %v", err)
	}
	if len(asst.ToolCalls) != 1 || asst.ToolCalls[0].Name != "list_applications" {
		t.Fatalf("unexpected tool calls: %+v", asst.ToolCalls)
	}
	if string(asst.ToolCalls[0].Args) != `{"status":"offer"}` {
		t.Fatalf("unexpected args: %s", asst.ToolCalls[0].Args)
	}
	if gotBody["tools"] == nil || gotBody["system"] == nil {
		t.Fatal("request missing tools/system")
	}
}

func TestCompleteAnthropicParsesText(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"你好"}],"stop_reason":"end_turn"}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL + "/anthropic", Model: "claude-3"})
	asst, err := c.Complete(context.Background(), []Message{{Role: RoleUser, Content: "hi"}}, nil)
	if err != nil {
		t.Fatalf("complete: %v", err)
	}
	if asst.Content != "你好" || len(asst.ToolCalls) != 0 {
		t.Fatalf("unexpected: %+v", asst)
	}
}
```

注意：现有 `chatAnthropic` 把 URL 拼为 `c.baseURL + "/v1/messages"`。为保持一致，适配器也用同一路径，测试 server 对任意路径都返回上面的 JSON，无需精确匹配路径。

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/ai/ -run TestCompleteAnthropic -v`
Expected: 编译失败（undefined completeAnthropic）。

- [ ] **Step 3: 实现 completeAnthropic**

Create `internal/ai/complete_anthropic.go`:

```go
package ai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type antTool struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	InputSchema json.RawMessage `json:"input_schema"`
}

type antBlock struct {
	Type      string          `json:"type"`
	Text      string          `json:"text,omitempty"`
	ID        string          `json:"id,omitempty"`
	Name      string          `json:"name,omitempty"`
	Input     json.RawMessage `json:"input,omitempty"`
	ToolUseID string          `json:"tool_use_id,omitempty"`
	Content   string          `json:"content,omitempty"`
}

type antMessage struct {
	Role    string     `json:"role"`
	Content []antBlock `json:"content"`
}

type antRequest struct {
	Model     string       `json:"model"`
	System    string       `json:"system,omitempty"`
	Messages  []antMessage `json:"messages"`
	Tools     []antTool    `json:"tools,omitempty"`
	MaxTokens int          `json:"max_tokens"`
}

type antResponse struct {
	Content []antBlock `json:"content"`
	Error   *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

func (c *Client) completeAnthropic(ctx context.Context, messages []Message, tools []Tool) (*Assistant, error) {
	req := antRequest{Model: c.model, MaxTokens: 4096}
	for _, m := range messages {
		switch m.Role {
		case RoleSystem:
			if req.System != "" {
				req.System += "\n"
			}
			req.System += m.Content
		case RoleUser:
			req.Messages = append(req.Messages, antMessage{
				Role:    "user",
				Content: []antBlock{{Type: "text", Text: m.Content}},
			})
		case RoleAssistant:
			blocks := []antBlock{}
			if m.Content != "" {
				blocks = append(blocks, antBlock{Type: "text", Text: m.Content})
			}
			for _, tc := range m.ToolCalls {
				input := tc.Args
				if len(input) == 0 {
					input = json.RawMessage(`{}`)
				}
				blocks = append(blocks, antBlock{Type: "tool_use", ID: tc.ID, Name: tc.Name, Input: input})
			}
			req.Messages = append(req.Messages, antMessage{Role: "assistant", Content: blocks})
		case RoleTool:
			// Anthropic carries tool results as a user message with a tool_result block.
			req.Messages = append(req.Messages, antMessage{
				Role:    "user",
				Content: []antBlock{{Type: "tool_result", ToolUseID: m.ToolCallID, Content: m.Content}},
			})
		}
	}
	for _, t := range tools {
		req.Tools = append(req.Tools, antTool{Name: t.Name, Description: t.Description, InputSchema: t.Schema})
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/v1/messages", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", c.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("call AI API: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		if len(tools) > 0 && isToolsUnsupportedBody(string(raw)) {
			return nil, fmt.Errorf("%w: %s", ErrToolsUnsupported, truncate(string(raw), 200))
		}
		return nil, fmt.Errorf("AI API returned %d: %s", resp.StatusCode, truncate(string(raw), 200))
	}

	var ar antResponse
	if err := json.Unmarshal(raw, &ar); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}
	asst := &Assistant{}
	for _, b := range ar.Content {
		switch b.Type {
		case "text", "":
			asst.Content += b.Text
		case "tool_use":
			input := b.Input
			if len(input) == 0 {
				input = json.RawMessage(`{}`)
			}
			asst.ToolCalls = append(asst.ToolCalls, ToolCall{ID: b.ID, Name: b.Name, Args: input})
		}
	}
	return asst, nil
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `go test ./internal/ai/ -run TestCompleteAnthropic -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/ai/complete_anthropic.go internal/ai/complete_test.go
git commit -m "feat(ai): Anthropic Complete adapter with tool_use/tool_result"
```

---

## Task 6: 降级模式 RunSummaryFallback

**Files:**
- Create: `internal/ai/summary.go`
- Test: `internal/ai/summary_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/ai/summary_test.go`:

```go
package ai

import (
	"context"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestBuildDataSummaryIncludesApplications(t *testing.T) {
	d, err := db.Init(t.TempDir() + "/s.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	defer d.Close()
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})

	summary := BuildDataSummary(d)
	if !strings.Contains(summary, "字节") || !strings.Contains(summary, "interview") {
		t.Fatalf("summary missing application info: %s", summary)
	}
}
```

（`RunSummaryFallback` 直接复用现有 `Client.Chat`，无需新建 HTTP mock；本任务只测纯函数 `BuildDataSummary`。`RunSummaryFallback` 的端到端行为在 Task 8 的 API 测试里覆盖。）

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/ai/ -run TestBuildDataSummary -v`
Expected: 编译失败（undefined BuildDataSummary）。

- [ ] **Step 3: 实现 summary.go**

Create `internal/ai/summary.go`:

```go
package ai

import (
	"context"
	"fmt"
	"strings"

	"github.com/offercontext/offerpilot/internal/db"
)

// BuildDataSummary produces a compact, token-light overview of the user's job
// data for injection into the system prompt when tool calling is unavailable.
func BuildDataSummary(database *db.Database) string {
	var sb strings.Builder
	sb.WriteString("以下是用户当前的求职数据摘要（只读）：\n")

	apps, err := database.ListApplications("")
	if err == nil {
		sb.WriteString(fmt.Sprintf("投递记录共 %d 条：\n", len(apps)))
		max := len(apps)
		if max > 30 {
			max = 30
		}
		for _, a := range apps[:max] {
			sb.WriteString(fmt.Sprintf("- #%d %s / %s [%s]\n", a.ID, a.CompanyName, a.PositionName, a.Status))
		}
		if len(apps) > max {
			sb.WriteString(fmt.Sprintf("…（其余 %d 条省略）\n", len(apps)-max))
		}
	}

	notes, err := database.ListInterviewNotes(0)
	if err == nil && len(notes) > 0 {
		sb.WriteString(fmt.Sprintf("面试复盘笔记共 %d 条。\n", len(notes)))
	}
	resumes, err := database.ListResumes()
	if err == nil && len(resumes) > 0 {
		sb.WriteString(fmt.Sprintf("简历共 %d 份。\n", len(resumes)))
	}
	return sb.String()
}

// RunSummaryFallback handles a single user turn without tools by injecting a
// data summary into the system prompt. Used when the model can't do tool calls.
func RunSummaryFallback(ctx context.Context, c *Client, database *db.Database, userMessage string) (string, error) {
	system := ChatSystemPrompt + "\n\n（注意：当前模型不支持工具调用，以下为只读数据摘要，你无法修改数据。）\n" + BuildDataSummary(database)
	return c.Chat(ctx, system, userMessage)
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `go test ./internal/ai/ -run TestBuildDataSummary -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/ai/summary.go internal/ai/summary_test.go
git commit -m "feat(ai): summary-injection fallback for models without tool calling"
```

---

## Task 7: 配置增加 ChatAutoApproveWrites + CLI 开关

**Files:**
- Modify: `internal/config/config.go`
- Modify: `internal/cli/root.go`
- Test: `internal/config/config_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/config/config_test.go`:

```go
package config

import "testing"

func TestSaveLoadAutoApprove(t *testing.T) {
	dir := t.TempDir()
	cfg := &Config{APIKey: "k", BaseURL: DefaultBaseURL, Model: DefaultModel, ChatAutoApproveWrites: true}
	if err := Save(dir, cfg); err != nil {
		t.Fatalf("save: %v", err)
	}
	got, err := Load(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if !got.ChatAutoApproveWrites {
		t.Fatal("expected ChatAutoApproveWrites to persist as true")
	}
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/config/ -run TestSaveLoadAutoApprove -v`
Expected: 编译失败（unknown field ChatAutoApproveWrites）。

- [ ] **Step 3: 增加配置字段**

In `internal/config/config.go`，给 `Config` 结构体增加字段：

```go
	LocalPort int    `json:"local_port"`
	// ChatAutoApproveWrites lets the AI assistant execute write tools without
	// asking the user to confirm each one. Defaults to false (confirm required).
	ChatAutoApproveWrites bool `json:"chat_auto_approve_writes"`
```

- [ ] **Step 4: 运行测试确认通过**

Run: `go test ./internal/config/ -run TestSaveLoadAutoApprove -v`
Expected: PASS

- [ ] **Step 5: 增加 CLI 开关**

In `internal/cli/root.go`：

在 `var (... cfgModel string)` 块中增加：

```go
	cfgAutoApprove bool
```

在 `newConfigCmd` 的 flags 注册后增加：

```go
	cmd.Flags().BoolVar(&cfgAutoApprove, "auto-approve", false, "let the AI assistant run write actions without confirmation")
```

在 `runConfig` 的 `if cmd.Flags().Changed("model")` 块之后增加：

```go
	if cmd.Flags().Changed("auto-approve") {
		cfg.ChatAutoApproveWrites = cfgAutoApprove
		changed = true
	}
```

在配置打印区（`fmt.Printf("  local_port: %d\n", cfg.LocalPort)` 之后）增加：

```go
	fmt.Printf("  ai_auto_approve: %v\n", cfg.ChatAutoApproveWrites)
```

- [ ] **Step 6: 编译确认**

Run: `go build ./...`
Expected: 无错误。

- [ ] **Step 7: 提交**

```bash
git add internal/config/config.go internal/config/config_test.go internal/cli/root.go
git commit -m "feat(config): chat_auto_approve_writes setting and oc config --auto-approve"
```

---

## Task 8: API 层 chat / settings 接口

**Files:**
- Create: `internal/api/chat.go`
- Create: `internal/api/settings.go`
- Modify: `internal/api/router.go`
- Test: `internal/api/chat_test.go`

- [ ] **Step 1: 写失败测试**

Create `internal/api/chat_test.go`:

```go
package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

func chatTestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/c.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

// fakeModel scripts assistant turns for the loop.
type fakeModel struct {
	turns []ai.Assistant
	i     int
}

func (m *fakeModel) Complete(_ context.Context, _ []ai.Message, _ []ai.Tool) (*ai.Assistant, error) {
	a := m.turns[m.i]
	m.i++
	return &a, nil
}

func TestChatTextReply(t *testing.T) {
	d := chatTestDB(t)
	model := &fakeModel{turns: []ai.Assistant{{Content: "你好，我能帮你管理求职进度。"}}}
	h := chatHandlerWithModel(d, model, false)

	body, _ := json.Marshal(map[string]interface{}{"message": "你好"})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	h(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	var resp map[string]interface{}
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp["type"] != "message" || resp["message"] == "" {
		t.Fatalf("unexpected response: %v", resp)
	}
	convID := int64(resp["conversation_id"].(float64))
	msgs, _ := d.ListMessages(convID)
	if len(msgs) != 2 { // user + assistant
		t.Fatalf("want 2 persisted messages, got %d", len(msgs))
	}
}

func TestChatWriteRequiresConfirmation(t *testing.T) {
	d := chatTestDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})
	model := &fakeModel{turns: []ai.Assistant{
		{ToolCalls: []ai.ToolCall{{ID: "w1", Name: "update_application_status", Args: json.RawMessage(`{"id":1,"status":"offer"}`)}}},
	}}
	h := chatHandlerWithModel(d, model, false)

	body, _ := json.Marshal(map[string]interface{}{"message": "把字节标记 offer"})
	req := httptest.NewRequest(http.MethodPost, "/api/chat", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	h(rec, req)

	var resp map[string]interface{}
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	if resp["type"] != "confirmation_required" {
		t.Fatalf("expected confirmation_required, got %v", resp)
	}
	app, _ := d.GetApplication(1)
	if app.Status == "offer" {
		t.Fatal("write should not execute before confirm")
	}
}
```

说明：测试通过一个可注入 model 的内部构造函数 `chatHandlerWithModel` 来绕过真实 HTTP。生产 handler 用 `ai.New(cfg)` 构造真实 `*ai.Client`（实现了 `ai.ChatModel`）。

- [ ] **Step 2: 运行测试确认失败**

Run: `go test ./internal/api/ -run TestChat -v`
Expected: 编译失败（undefined chatHandlerWithModel 等）。

- [ ] **Step 3: 实现 chat.go**

Create `internal/api/chat.go`:

```go
package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

// registerChatRoutes wires the chat endpoints onto the /api group.
func registerChatRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Post("/chat", chatHandler(database, dataDir))
	r.Post("/chat/confirm", chatConfirmHandler(database, dataDir))
	r.Get("/chat/conversations", listConversationsHandler(database))
	r.Get("/chat/conversations/{id}", getConversationHandler(database))
	r.Delete("/chat/conversations/{id}", deleteConversationHandler(database))
}

type chatRequestBody struct {
	ConversationID int64  `json:"conversation_id"`
	Message        string `json:"message"`
}

type confirmRequestBody struct {
	ConversationID int64 `json:"conversation_id"`
	Approved       bool  `json:"approved"`
}

// toAIMessages converts stored messages into the protocol-agnostic form,
// prepending the system prompt.
func toAIMessages(stored []db.ChatMessage) []ai.Message {
	out := []ai.Message{{Role: ai.RoleSystem, Content: ai.ChatSystemPrompt}}
	for _, m := range stored {
		msg := ai.Message{Role: ai.Role(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if m.ToolCalls != "" {
			var tcs []ai.ToolCall
			if json.Unmarshal([]byte(m.ToolCalls), &tcs) == nil {
				msg.ToolCalls = tcs
			}
		}
		out = append(out, msg)
	}
	return out
}

// persistAdded stores loop-produced messages into the conversation.
func persistAdded(database *db.Database, convID int64, added []ai.Message) error {
	for _, m := range added {
		cm := &db.ChatMessage{ConversationID: convID, Role: string(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if len(m.ToolCalls) > 0 {
			b, _ := json.Marshal(m.ToolCalls)
			cm.ToolCalls = string(b)
		}
		if err := database.AppendMessage(cm); err != nil {
			return err
		}
	}
	return nil
}

func titleFrom(msg string) string {
	const max = 20
	if utf8.RuneCountInString(msg) <= max {
		return msg
	}
	rs := []rune(msg)
	return string(rs[:max]) + "…"
}

// chatHandler is the production handler; it builds a real AI client from config.
func chatHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		client, err := ai.New(cfg)
		if err != nil {
			respondError(w, http.StatusServiceUnavailable, err.Error())
			return
		}
		runChat(w, r, database, client, cfg.ChatAutoApproveWrites, dataDir, client)
	}
}

// chatHandlerWithModel injects a model + auto-approve flag for testing.
func chatHandlerWithModel(database *db.Database, model ai.ChatModel, autoApprove bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		runChat(w, r, database, model, autoApprove, "", nil)
	}
}

// runChat contains the shared logic. fallbackClient may be nil (tests) — when
// non-nil it is used for summary-mode downgrade.
func runChat(w http.ResponseWriter, r *http.Request, database *db.Database, model ai.ChatModel, autoApprove bool, dataDir string, fallbackClient *ai.Client) {
	var body chatRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Message == "" {
		respondError(w, http.StatusBadRequest, "message is required")
		return
	}

	convID := body.ConversationID
	if convID == 0 {
		conv, err := database.CreateConversation(titleFrom(body.Message))
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		convID = conv.ID
	}
	if err := database.AppendMessage(&db.ChatMessage{ConversationID: convID, Role: "user", Content: body.Message}); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}

	stored, err := database.ListMessages(convID)
	if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	reg := ai.NewRegistry(database)
	added, reply, pending, err := ai.RunTurn(r.Context(), model, reg, toAIMessages(stored), autoApprove, ai.DefaultMaxIterations)

	if errors.Is(err, ai.ErrToolsUnsupported) && fallbackClient != nil {
		text, ferr := ai.RunSummaryFallback(r.Context(), fallbackClient, database, body.Message)
		if ferr != nil {
			respondError(w, http.StatusBadGateway, ferr.Error())
			return
		}
		_ = database.AppendMessage(&db.ChatMessage{ConversationID: convID, Role: "assistant", Content: text})
		respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": convID, "message": text, "degraded": true})
		return
	}
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := persistAdded(database, convID, added); perr != nil {
		respondError(w, http.StatusInternalServerError, perr.Error())
		return
	}

	if pending != nil {
		respondJSON(w, http.StatusOK, map[string]interface{}{
			"type":            "confirmation_required",
			"conversation_id": convID,
			"pending_action":  map[string]interface{}{"tool_name": pending.ToolName, "human": pending.Human},
		})
		return
	}
	respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": convID, "message": reply})
}

func chatConfirmHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		client, err := ai.New(cfg)
		if err != nil {
			respondError(w, http.StatusServiceUnavailable, err.Error())
			return
		}
		runConfirm(w, r, database, client, cfg.ChatAutoApproveWrites)
	}
}

func runConfirm(w http.ResponseWriter, r *http.Request, database *db.Database, model ai.ChatModel, autoApprove bool) {
	var body confirmRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.ConversationID == 0 {
		respondError(w, http.StatusBadRequest, "conversation_id is required")
		return
	}
	stored, err := database.ListMessages(body.ConversationID)
	if err != nil || len(stored) == 0 {
		respondError(w, http.StatusNotFound, "conversation not found")
		return
	}
	// The last message must be an assistant turn carrying the pending write call.
	last := stored[len(stored)-1]
	if last.Role != "assistant" || last.ToolCalls == "" {
		respondError(w, http.StatusBadRequest, "no pending action to confirm")
		return
	}
	var tcs []ai.ToolCall
	if json.Unmarshal([]byte(last.ToolCalls), &tcs) != nil || len(tcs) == 0 {
		respondError(w, http.StatusBadRequest, "malformed pending action")
		return
	}
	pending := &ai.PendingAction{ToolCallID: tcs[0].ID, ToolName: tcs[0].Name, Args: tcs[0].Args}

	reg := ai.NewRegistry(database)
	added, reply, newPending, err := ai.ResumeAfterConfirm(r.Context(), model, reg, toAIMessages(stored), pending, body.Approved, autoApprove, ai.DefaultMaxIterations)
	if err != nil {
		respondError(w, http.StatusBadGateway, err.Error())
		return
	}
	if perr := persistAdded(database, body.ConversationID, added); perr != nil {
		respondError(w, http.StatusInternalServerError, perr.Error())
		return
	}
	if newPending != nil {
		respondJSON(w, http.StatusOK, map[string]interface{}{
			"type":            "confirmation_required",
			"conversation_id": body.ConversationID,
			"pending_action":  map[string]interface{}{"tool_name": newPending.ToolName, "human": newPending.Human},
		})
		return
	}
	respondJSON(w, http.StatusOK, map[string]interface{}{"type": "message", "conversation_id": body.ConversationID, "message": reply})
}

func listConversationsHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		convs, err := database.ListConversations()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, convs)
	}
}

func getConversationHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		msgs, err := database.ListMessages(id)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, msgs)
	}
}

func deleteConversationHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid id")
			return
		}
		if err := database.DeleteConversation(id); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
	}
}
```

- [ ] **Step 4: 实现 settings.go**

Create `internal/api/settings.go`:

```go
package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/config"
)

// registerSettingsRoutes wires chat-related settings (never exposes the API key).
func registerSettingsRoutes(r chi.Router, dataDir string) {
	r.Get("/settings", getSettingsHandler(dataDir))
	r.Put("/settings", putSettingsHandler(dataDir))
}

type settingsDTO struct {
	ChatAutoApproveWrites bool   `json:"chat_auto_approve_writes"`
	Model                 string `json:"model"`
	HasAPIKey             bool   `json:"has_api_key"`
}

func getSettingsHandler(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, settingsDTO{
			ChatAutoApproveWrites: cfg.ChatAutoApproveWrites,
			Model:                 cfg.Model,
			HasAPIKey:             cfg.APIKey != "",
		})
	}
}

func putSettingsHandler(dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ChatAutoApproveWrites bool `json:"chat_auto_approve_writes"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			respondError(w, http.StatusBadRequest, "invalid body")
			return
		}
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		cfg.ChatAutoApproveWrites = body.ChatAutoApproveWrites
		if err := config.Save(dataDir, cfg); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, settingsDTO{
			ChatAutoApproveWrites: cfg.ChatAutoApproveWrites,
			Model:                 cfg.Model,
			HasAPIKey:             cfg.APIKey != "",
		})
	}
}
```

- [ ] **Step 5: 注册路由**

In `internal/api/router.go`，在 `r.Get("/calendar", ...)` 行之后增加：

```go
			// AI chat assistant
			registerChatRoutes(r, database, dataDir)
			// Chat-related settings (no API key exposure)
			registerSettingsRoutes(r, dataDir)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `go test ./internal/api/ -run TestChat -v`
Expected: PASS

- [ ] **Step 7: 全量编译 + 测试**

Run: `go build ./... && go test ./...`
Expected: 全部 PASS

- [ ] **Step 8: 提交**

```bash
git add internal/api/chat.go internal/api/settings.go internal/api/router.go internal/api/chat_test.go
git commit -m "feat(api): chat endpoints with confirmation flow and settings"
```

---

## Task 9: 前端类型与服务

**Files:**
- Create: `web/src/types/chat.ts`
- Create: `web/src/services/chat.ts`

- [ ] **Step 1: 定义类型**

Create `web/src/types/chat.ts`:

```ts
export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: string;
  tool_call_id?: string;
  created_at: string;
}

export interface PendingAction {
  tool_name: string;
  human: string;
}

export type ChatResponse =
  | { type: 'message'; conversation_id: number; message: string; degraded?: boolean }
  | { type: 'confirmation_required'; conversation_id: number; pending_action: PendingAction };
```

- [ ] **Step 2: 实现服务**

Create `web/src/services/chat.ts`:

```ts
import axios from 'axios';
import type { ChatMessage, ChatResponse, Conversation } from '@/types/chat';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

export async function sendChat(message: string, conversationId?: number): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat', {
    message,
    conversation_id: conversationId ?? 0,
  });
  return data;
}

export async function confirmAction(conversationId: number, approved: boolean): Promise<ChatResponse> {
  const { data } = await http.post<ChatResponse>('/chat/confirm', {
    conversation_id: conversationId,
    approved,
  });
  return data;
}

export async function listConversations(): Promise<Conversation[]> {
  const { data } = await http.get<Conversation[]>('/chat/conversations');
  return data ?? [];
}

export async function getConversation(id: number): Promise<ChatMessage[]> {
  const { data } = await http.get<ChatMessage[]>(`/chat/conversations/${id}`);
  return data ?? [];
}

export async function deleteConversation(id: number): Promise<void> {
  await http.delete(`/chat/conversations/${id}`);
}

export interface Settings {
  chat_auto_approve_writes: boolean;
  model: string;
  has_api_key: boolean;
}

export async function getSettings(): Promise<Settings> {
  const { data } = await http.get<Settings>('/settings');
  return data;
}

export async function updateAutoApprove(value: boolean): Promise<Settings> {
  const { data } = await http.put<Settings>('/settings', { chat_auto_approve_writes: value });
  return data;
}
```

- [ ] **Step 3: 类型检查**

Run: `cd web && npx tsc -b --noEmit`
Expected: 无类型错误（若因后续未创建组件而报错，等 Task 10 完成后统一验证）。

- [ ] **Step 4: 提交**

```bash
git add web/src/types/chat.ts web/src/services/chat.ts
git commit -m "feat(web): chat types and API service"
```

---

## Task 10: 前端 ChatPanel 组件与入口

**Files:**
- Modify: `web/package.json`（增加 react-markdown）
- Create: `web/src/components/ChatPanel/ConfirmCard.tsx`
- Create: `web/src/components/ChatPanel/ChatPanel.module.css`
- Create: `web/src/components/ChatPanel/index.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: 安装 markdown 渲染依赖**

Run: `cd web && npm install react-markdown@^9`
Expected: `react-markdown` 写入 `package.json` dependencies。

- [ ] **Step 2: 确认卡片组件**

Create `web/src/components/ChatPanel/ConfirmCard.tsx`:

```tsx
import { Card, Button, Space, Typography } from 'antd';
import type { PendingAction } from '@/types/chat';

const { Text } = Typography;

interface Props {
  action: PendingAction;
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmCard({ action, loading, onConfirm, onCancel }: Props) {
  return (
    <Card size="small" style={{ borderColor: '#f59e0b', background: '#fffbeb', margin: '8px 0' }}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Text strong>AI 想执行一个修改操作：</Text>
        <Text>{action.human}</Text>
        <Space>
          <Button type="primary" loading={loading} onClick={onConfirm}>
            确认
          </Button>
          <Button disabled={loading} onClick={onCancel}>
            取消
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
```

- [ ] **Step 3: 样式**

Create `web/src/components/ChatPanel/ChatPanel.module.css`:

```css
.messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 4px;
}
.row {
  display: flex;
}
.rowUser {
  justify-content: flex-end;
}
.bubble {
  max-width: 80%;
  padding: 8px 12px;
  border-radius: 10px;
  line-height: 1.5;
  word-break: break-word;
}
.user {
  background: #059669;
  color: #fff;
}
.assistant {
  background: #f1f5f9;
  color: #1a1a1a;
}
.tool {
  align-self: center;
  font-size: 12px;
  color: #64748b;
}
.inputBar {
  display: flex;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #e2e8f0;
}
```

- [ ] **Step 4: 主面板**

Create `web/src/components/ChatPanel/index.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { Drawer, Input, Button, Switch, Space, Typography, App as AntApp } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {
  sendChat,
  confirmAction,
  getSettings,
  updateAutoApprove,
} from '@/services/chat';
import type { PendingAction } from '@/types/chat';
import ConfirmCard from './ConfirmCard';
import styles from './ChatPanel.module.css';

const { Text } = Typography;

interface UIMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ChatPanel({ open, onClose }: Props) {
  const { message: toast } = AntApp.useApp();
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState('');
  const [convID, setConvID] = useState<number | undefined>(undefined);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [hasKey, setHasKey] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    getSettings()
      .then((s) => {
        setAutoApprove(s.chat_auto_approve_writes);
        setHasKey(s.has_api_key);
      })
      .catch(() => undefined);
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pending]);

  function applyResponse(resp: Awaited<ReturnType<typeof sendChat>>) {
    setConvID(resp.conversation_id);
    if (resp.type === 'confirmation_required') {
      setPending(resp.pending_action);
    } else {
      setPending(null);
      setMessages((m) => [...m, { role: 'assistant', content: resp.message }]);
      if (resp.degraded) {
        toast.info('当前模型不支持工具调用，已切换为只读摘要模式');
      }
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setInput('');
    setLoading(true);
    try {
      const resp = await sendChat(text, convID);
      applyResponse(resp);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '对话失败');
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(approved: boolean) {
    if (!convID) return;
    setLoading(true);
    try {
      const resp = await confirmAction(convID, approved);
      applyResponse(resp);
    } catch (e: any) {
      toast.error(e?.response?.data?.error ?? '确认失败');
    } finally {
      setLoading(false);
    }
  }

  async function toggleAutoApprove(value: boolean) {
    setAutoApprove(value);
    try {
      await updateAutoApprove(value);
    } catch {
      setAutoApprove(!value);
      toast.error('设置保存失败');
    }
  }

  return (
    <Drawer title="AI 助手" placement="right" width={460} open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Space style={{ marginBottom: 8 }}>
          <Text type="secondary">写操作免确认</Text>
          <Switch checked={autoApprove} onChange={toggleAutoApprove} />
        </Space>

        {!hasKey && (
          <Text type="warning" style={{ marginBottom: 8 }}>
            尚未配置 API key，请先运行 `oc config --api-key sk-xxx`。
          </Text>
        )}

        <div className={styles.messages} style={{ flex: 1, overflowY: 'auto' }}>
          {messages.map((m, i) => (
            <div key={i} className={`${styles.row} ${m.role === 'user' ? styles.rowUser : ''}`}>
              <div className={`${styles.bubble} ${m.role === 'user' ? styles.user : styles.assistant}`}>
                {m.role === 'assistant' ? <ReactMarkdown>{m.content}</ReactMarkdown> : m.content}
              </div>
            </div>
          ))}
          {pending && (
            <ConfirmCard
              action={pending}
              loading={loading}
              onConfirm={() => handleConfirm(true)}
              onCancel={() => handleConfirm(false)}
            />
          )}
          <div ref={endRef} />
        </div>

        <div className={styles.inputBar}>
          <Input.TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="问问 AI 关于你的求职进度…"
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading || !!pending}
          />
          <Button type="primary" icon={<SendOutlined />} loading={loading} disabled={!!pending} onClick={handleSend} />
        </div>
      </div>
    </Drawer>
  );
}
```

注意：`AntApp.useApp()` 需要应用被 antd 的 `<App>` 包裹。检查 `web/src/main.tsx`：若根组件未包 `<App>`，在 Step 6 顺带加上。

- [ ] **Step 5: App 入口接线**

In `web/src/App.tsx`：

import 区增加：

```tsx
import { RobotOutlined } from '@ant-design/icons';
import ChatPanel from '@/components/ChatPanel';
```

state 区（`const [resumeOpen, setResumeOpen] = useState(false);` 之后）增加：

```tsx
  const [chatOpen, setChatOpen] = useState(false);
```

Header 的 `<Space>` 内、`简历匹配` 按钮之前增加：

```tsx
          <Button icon={<RobotOutlined />} onClick={() => setChatOpen(true)}>
            AI 助手
          </Button>
```

在 `<ResumeMatchModal ... />` 之后增加：

```tsx
      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
```

- [ ] **Step 6: 确保 antd App 包裹**

Read `web/src/main.tsx`。如果根渲染没有 antd `<App>` 包裹（`message.useApp` 依赖它），将根组件包一层。例如把渲染改为（保留已有 Provider）：

```tsx
import { App as AntApp } from 'antd';
// …
<AntApp>
  <App />
</AntApp>
```

若已存在 `<App>` 包裹则跳过。

- [ ] **Step 7: 构建验证**

Run: `cd web && npm run build`
Expected: 构建成功，无类型错误。

- [ ] **Step 8: 手动验证（端到端）**

1. `go build -o oc ./cmd/oc && ./oc config --api-key <你的key> --base-url <endpoint> --model <model>`
2. `cd web && npm run build`，回到根目录 `./oc start`
3. 浏览器打开，点「AI 助手」，问「我现在有几条投递？」→ AI 应调用工具并回答
4. 说「把 XX 公司标记为 offer」→ 出现确认卡片，点确认后状态更新
5. 打开「写操作免确认」开关，再让它改一次 → 不弹确认直接执行

- [ ] **Step 9: 提交**

```bash
git add web/package.json web/package-lock.json web/src/components/ChatPanel web/src/App.tsx web/src/main.tsx
git commit -m "feat(web): AI chat panel with tool-calling and write confirmation"
```

---

## Self-Review 结果

- **Spec 覆盖**：架构(Task 1-10)、tool calling(Task 2-3)、双协议(Task 4-5)、降级(Task 6)、写确认中断-恢复(Task 3,8)、多会话持久化(Task 1,8)、配置开关(Task 7)、前端面板含确认卡片/工具提示/免确认开关(Task 10)、错误处理(各 handler) 均有对应任务。✅
- **前端测试偏差**：spec 第 10 节列了「确认卡片组件测试」，因 `web/` 无测试框架，本计划改为构建+手动验证（Task 10 Step 7-8），避免引入 vitest 的范围蔓延。这是与 spec 的唯一有意偏差。
- **类型一致性**：`RunTurn` / `ResumeAfterConfirm` / `PendingAction` / `ChatModel` / `Complete` / `Assistant` / `ToolCall.Args(json.RawMessage)` 在 Go 各任务间签名一致；前端 `ChatResponse` 联合类型与后端 `type` 字段(`message`/`confirmation_required`)一致。✅
- **占位符**：无 TBD/TODO，每个代码步骤均为完整可用代码。✅
```