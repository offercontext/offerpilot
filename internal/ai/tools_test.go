package ai

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

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

func TestScheduleEventTools(t *testing.T) {
	d := newToolDB(t)
	_ = d.CreateApplication(&db.Application{
		CompanyName: "Tencent", PositionName: "Backend", Status: "interview", Source: "test",
		AppliedAt: time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC),
	})
	reg := NewRegistry(d)

	createTool, ok := reg.Get("create_event")
	if !ok {
		t.Fatal("create_event should be registered")
	}
	if !createTool.Write {
		t.Fatal("create_event should be a write tool")
	}
	if !strings.Contains(string(createTool.Schema), `"duration_minutes":{"type":"integer"`) {
		t.Fatalf("create_event duration_minutes should be an integer schema, got %s", createTool.Schema)
	}
	createArgs := json.RawMessage(`{"application_id":1,"event_type":"interview","scheduled_at":"2026-07-03T14:00:00Z","duration_minutes":60,"location":"腾讯会议"}`)
	if createTool.Describe(createArgs) == "" {
		t.Fatal("create_event should describe confirmation text")
	}

	out, err := reg.Execute(context.Background(), "create_event", createArgs)
	if err != nil {
		t.Fatalf("execute create_event: %v", err)
	}
	if !strings.Contains(out, `"event_type":"interview"`) {
		t.Fatalf("expected event type in output, got %s", out)
	}

	out, err = reg.Execute(context.Background(), "list_events", json.RawMessage(`{"month":"2026-07"}`))
	if err != nil {
		t.Fatalf("execute list_events: %v", err)
	}
	if !strings.Contains(out, "腾讯会议") {
		t.Fatalf("expected location in output, got %s", out)
	}

	updateTool, ok := reg.Get("update_event")
	if !ok || !updateTool.Write {
		t.Fatal("update_event should be a write tool")
	}
	if !strings.Contains(string(updateTool.Schema), `"duration_minutes":{"type":"integer"`) {
		t.Fatalf("update_event duration_minutes should be an integer schema, got %s", updateTool.Schema)
	}
	deleteTool, ok := reg.Get("delete_event")
	if !ok || !deleteTool.Write {
		t.Fatal("delete_event should be a write tool")
	}

	out, err = reg.Execute(context.Background(), "update_event", json.RawMessage(`{"id":1,"application_id":1,"event_type":"interview","scheduled_at":"2026-07-03T15:00:00Z","duration_minutes":90,"location":"腾讯会议","notes":"technical round"}`))
	if err != nil {
		t.Fatalf("execute update_event: %v", err)
	}
	if !strings.Contains(out, `"duration":"90m"`) {
		t.Fatalf("expected updated duration in output, got %s", out)
	}

	out, err = reg.Execute(context.Background(), "delete_event", json.RawMessage(`{"id":1}`))
	if err != nil {
		t.Fatalf("execute delete_event: %v", err)
	}
	if !strings.Contains(out, `"deleted":true`) {
		t.Fatalf("expected delete confirmation, got %s", out)
	}
}

func TestScheduleEventToolsValidateEventType(t *testing.T) {
	d := newToolDB(t)
	_ = d.CreateApplication(&db.Application{
		CompanyName: "Tencent", PositionName: "Backend", Status: "interview", Source: "test",
		AppliedAt: time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC),
	})
	reg := NewRegistry(d)

	_, err := reg.Execute(context.Background(), "create_event", json.RawMessage(`{"application_id":1,"event_type":"onsite","scheduled_at":"2026-07-03T14:00:00Z","duration_minutes":60}`))
	if err == nil {
		t.Fatal("expected invalid event_type error for create_event")
	}
	events, err := d.ListEvents(db.EventFilter{})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(events) != 0 {
		t.Fatalf("invalid create_event should not create rows, got %+v", events)
	}

	scheduledAt := time.Date(2026, 7, 3, 14, 0, 0, 0, time.UTC)
	event := &db.Event{
		ApplicationID: 1,
		EventType:     "interview",
		ScheduledAt:   &scheduledAt,
		Duration:      "60m",
	}
	if err := d.CreateEvent(event); err != nil {
		t.Fatalf("create event: %v", err)
	}
	_, err = reg.Execute(context.Background(), "update_event", json.RawMessage(`{"id":1,"application_id":1,"event_type":"onsite","scheduled_at":"2026-07-03T15:00:00Z","duration_minutes":90}`))
	if err == nil {
		t.Fatal("expected invalid event_type error for update_event")
	}
	got, err := d.GetEvent(event.ID)
	if err != nil {
		t.Fatalf("get event: %v", err)
	}
	if got.EventType != "interview" || got.Duration != "60m" {
		t.Fatalf("invalid update_event should not change row, got %+v", got)
	}
}

func TestInterviewNoteToolsCRUD(t *testing.T) {
	d := newToolDB(t)
	_ = d.CreateApplication(&db.Application{
		CompanyName: "ByteDance", PositionName: "Backend", Status: "interview", Source: "test",
		AppliedAt: time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC),
	})
	reg := NewRegistry(d)

	addTool, ok := reg.Get("add_note")
	if !ok || !addTool.Write {
		t.Fatal("add_note should be a write tool")
	}
	if !strings.Contains(string(addTool.Schema), `"difficulty_points"`) {
		t.Fatalf("add_note schema should include difficulty_points, got %s", addTool.Schema)
	}

	createArgs := json.RawMessage(`{"application_id":1,"round":"Round 1","date":"2026-07-01","questions":"Go scheduler","self_reflection":"Clear structure","difficulty_points":"Runtime internals","mood":"good"}`)
	out, err := reg.Execute(context.Background(), "add_note", createArgs)
	if err != nil {
		t.Fatalf("execute add_note: %v", err)
	}
	if !strings.Contains(out, `"company":"ByteDance"`) || !strings.Contains(out, `"difficulty_points":"Runtime internals"`) {
		t.Fatalf("expected backfilled note output, got %s", out)
	}

	updateTool, ok := reg.Get("update_note")
	if !ok || !updateTool.Write {
		t.Fatal("update_note should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "update_note", json.RawMessage(`{"id":1,"self_reflection":"Need deeper runtime examples","mood":"normal"}`))
	if err != nil {
		t.Fatalf("execute update_note: %v", err)
	}
	if !strings.Contains(out, `"round":"Round 1"`) || !strings.Contains(out, `"self_reflection":"Need deeper runtime examples"`) {
		t.Fatalf("expected partial update preserving existing fields, got %s", out)
	}

	deleteTool, ok := reg.Get("delete_note")
	if !ok || !deleteTool.Write {
		t.Fatal("delete_note should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "delete_note", json.RawMessage(`{"id":1}`))
	if err != nil {
		t.Fatalf("execute delete_note: %v", err)
	}
	if !strings.Contains(out, `"deleted":true`) {
		t.Fatalf("expected delete confirmation, got %s", out)
	}
}

func TestInterviewNoteToolsValidateMissingCompany(t *testing.T) {
	reg := NewRegistry(newToolDB(t))
	_, err := reg.Execute(context.Background(), "add_note", json.RawMessage(`{"round":"Round 1"}`))
	if err == nil {
		t.Fatal("expected missing company error")
	}
}
