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
