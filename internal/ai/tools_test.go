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
