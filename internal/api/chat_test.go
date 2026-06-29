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
