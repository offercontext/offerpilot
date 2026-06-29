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
