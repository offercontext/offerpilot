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
