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

func TestCompleteAnthropicPreservesThinkingBlocksForToolFollowup(t *testing.T) {
	var calls int
	var followupBody map[string]interface{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		calls++
		if calls == 1 {
			_, _ = w.Write([]byte(`{"content":[{"type":"thinking","thinking":"checking schedules","signature":"sig_1"},{"type":"tool_use","id":"toolu_1","name":"list_schedule_events","input":{"event_type":"all"}}],"stop_reason":"tool_use"}`))
			return
		}
		_ = json.Unmarshal(raw, &followupBody)
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn"}`))
	}))
	defer srv.Close()

	c, _ := New(&config.Config{APIKey: "k", BaseURL: srv.URL + "/anthropic", Model: "claude-3"})
	tools := []Tool{{Name: "list_schedule_events", Description: "x", Schema: json.RawMessage(`{"type":"object"}`)}}
	asst, err := c.Complete(context.Background(), []Message{{Role: RoleUser, Content: "hi"}}, tools)
	if err != nil {
		t.Fatalf("first complete: %v", err)
	}
	if len(asst.ToolCalls) != 1 {
		t.Fatalf("unexpected tool calls: %+v", asst.ToolCalls)
	}
	if len(asst.ProviderBlocks) != 1 {
		t.Fatalf("expected thinking provider block, got %d", len(asst.ProviderBlocks))
	}

	_, err = c.Complete(context.Background(), []Message{
		{Role: RoleUser, Content: "hi"},
		{Role: RoleAssistant, ToolCalls: asst.ToolCalls, ProviderBlocks: asst.ProviderBlocks},
		{Role: RoleTool, ToolCallID: "toolu_1", Content: "[]"},
	}, tools)
	if err != nil {
		t.Fatalf("followup complete: %v", err)
	}

	messages, ok := followupBody["messages"].([]interface{})
	if !ok || len(messages) < 2 {
		t.Fatalf("unexpected followup messages: %#v", followupBody["messages"])
	}
	assistantMsg, ok := messages[1].(map[string]interface{})
	if !ok {
		t.Fatalf("unexpected assistant message: %#v", messages[1])
	}
	content, ok := assistantMsg["content"].([]interface{})
	if !ok || len(content) == 0 {
		t.Fatalf("unexpected assistant content: %#v", assistantMsg["content"])
	}
	thinking, ok := content[0].(map[string]interface{})
	if !ok || thinking["type"] != "thinking" || thinking["thinking"] != "checking schedules" || thinking["signature"] != "sig_1" {
		t.Fatalf("thinking block not preserved: %#v", content)
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
