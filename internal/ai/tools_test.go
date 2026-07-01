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

func TestKnowledgeToolsCRUDAndSearch(t *testing.T) {
	d := newToolDB(t)
	reg := NewRegistry(d)

	createBase, ok := reg.Get("create_knowledge_base")
	if !ok || !createBase.Write {
		t.Fatal("create_knowledge_base should be a write tool")
	}
	if createBase.Describe(json.RawMessage(`{"name":"Java interview prep"}`)) == "" {
		t.Fatal("create_knowledge_base should describe confirmation text")
	}

	out, err := reg.Execute(context.Background(), "create_knowledge_base", json.RawMessage(`{"name":"Java interview prep","description":"core notes"}`))
	if err != nil {
		t.Fatalf("create base: %v", err)
	}
	if !strings.Contains(out, `"name":"Java interview prep"`) {
		t.Fatalf("unexpected base output: %s", out)
	}

	createDoc, ok := reg.Get("create_knowledge_document")
	if !ok || !createDoc.Write {
		t.Fatal("create_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "create_knowledge_document", json.RawMessage(`{"knowledge_base_id":1,"title":"Synchronized","content":"monitor lock and happens-before","tags":["java"]}`))
	if err != nil {
		t.Fatalf("create doc: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized"`) {
		t.Fatalf("unexpected doc output: %s", out)
	}

	out, err = reg.Execute(context.Background(), "search_knowledge", json.RawMessage(`{"query":"monitor","limit":5}`))
	if err != nil {
		t.Fatalf("search knowledge: %v", err)
	}
	if !strings.Contains(out, `"document_title":"Synchronized"`) || !strings.Contains(out, `"snippet"`) {
		t.Fatalf("unexpected search output: %s", out)
	}

	updateDoc, ok := reg.Get("update_knowledge_document")
	if !ok || !updateDoc.Write {
		t.Fatal("update_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "update_knowledge_document", json.RawMessage(`{"id":1,"knowledge_base_id":1,"title":"Synchronized updated","content":"biased locking was removed","tags":["jvm"]}`))
	if err != nil {
		t.Fatalf("update doc: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized updated"`) {
		t.Fatalf("unexpected update output: %s", out)
	}

	deleteDoc, ok := reg.Get("delete_knowledge_document")
	if !ok || !deleteDoc.Write {
		t.Fatal("delete_knowledge_document should be a write tool")
	}
	out, err = reg.Execute(context.Background(), "delete_knowledge_document", json.RawMessage(`{"id":1}`))
	if err != nil {
		t.Fatalf("delete doc: %v", err)
	}
	if !strings.Contains(out, `"deleted":true`) {
		t.Fatalf("unexpected delete output: %s", out)
	}
}

func TestKnowledgeToolsReadAndPartialUpdates(t *testing.T) {
	d := newToolDB(t)
	reg := NewRegistry(d)

	_, err := reg.Execute(context.Background(), "create_knowledge_base", json.RawMessage(`{"name":"Java interview prep","description":"core notes"}`))
	if err != nil {
		t.Fatalf("create first base: %v", err)
	}
	_, err = reg.Execute(context.Background(), "create_knowledge_base", json.RawMessage(`{"name":"System design","description":"distributed notes"}`))
	if err != nil {
		t.Fatalf("create second base: %v", err)
	}

	out, err := reg.Execute(context.Background(), "list_knowledge_bases", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("list bases: %v", err)
	}
	if !strings.Contains(out, `"name":"Java interview prep"`) || !strings.Contains(out, `"name":"System design"`) {
		t.Fatalf("unexpected bases output: %s", out)
	}

	_, err = reg.Execute(context.Background(), "create_knowledge_document", json.RawMessage(`{"knowledge_base_id":1,"title":"Synchronized","content":"monitor lock and happens-before","tags":["java","concurrency"]}`))
	if err != nil {
		t.Fatalf("create first doc: %v", err)
	}
	_, err = reg.Execute(context.Background(), "create_knowledge_document", json.RawMessage(`{"knowledge_base_id":2,"title":"Consistent hashing","content":"ring vnode scaling","tags":["system"]}`))
	if err != nil {
		t.Fatalf("create second doc: %v", err)
	}

	out, err = reg.Execute(context.Background(), "list_knowledge_documents", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("list docs: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized"`) || !strings.Contains(out, `"title":"Consistent hashing"`) {
		t.Fatalf("unexpected docs output: %s", out)
	}

	out, err = reg.Execute(context.Background(), "list_knowledge_documents", json.RawMessage(`{"knowledge_base_id":1}`))
	if err != nil {
		t.Fatalf("list docs by base: %v", err)
	}
	if !strings.Contains(out, `"title":"Synchronized"`) || strings.Contains(out, `"title":"Consistent hashing"`) {
		t.Fatalf("knowledge_base_id filter not respected: %s", out)
	}

	out, err = reg.Execute(context.Background(), "list_knowledge_documents", json.RawMessage(`{"query":"vnode"}`))
	if err != nil {
		t.Fatalf("list docs by query: %v", err)
	}
	if !strings.Contains(out, `"title":"Consistent hashing"`) || strings.Contains(out, `"title":"Synchronized"`) {
		t.Fatalf("query filter not respected: %s", out)
	}

	out, err = reg.Execute(context.Background(), "get_knowledge_document", json.RawMessage(`{"id":1}`))
	if err != nil {
		t.Fatalf("get doc: %v", err)
	}
	if !strings.Contains(out, `"content":"monitor lock and happens-before"`) || !strings.Contains(out, `"tags":["java","concurrency"]`) {
		t.Fatalf("unexpected get doc output: %s", out)
	}

	updateBase, ok := reg.Get("update_knowledge_base")
	if !ok || !updateBase.Write {
		t.Fatal("update_knowledge_base should be a write tool")
	}
	if updateBase.Describe(json.RawMessage(`{"id":1,"name":"Java notes"}`)) == "" {
		t.Fatal("update_knowledge_base should describe confirmation text")
	}
	out, err = reg.Execute(context.Background(), "update_knowledge_base", json.RawMessage(`{"id":1,"name":"Java notes"}`))
	if err != nil {
		t.Fatalf("partial update base: %v", err)
	}
	if !strings.Contains(out, `"name":"Java notes"`) || !strings.Contains(out, `"description":"core notes"`) {
		t.Fatalf("base partial update should preserve omitted fields, got %s", out)
	}

	out, err = reg.Execute(context.Background(), "update_knowledge_document", json.RawMessage(`{"id":1,"title":"Monitor locks"}`))
	if err != nil {
		t.Fatalf("partial update doc: %v", err)
	}
	if !strings.Contains(out, `"title":"Monitor locks"`) ||
		!strings.Contains(out, `"knowledge_base_id":1`) ||
		!strings.Contains(out, `"content":"monitor lock and happens-before"`) ||
		!strings.Contains(out, `"tags":["java","concurrency"]`) {
		t.Fatalf("doc partial update should preserve omitted fields, got %s", out)
	}

	deleteBase, ok := reg.Get("delete_knowledge_base")
	if !ok || !deleteBase.Write {
		t.Fatal("delete_knowledge_base should be a write tool")
	}
	if deleteBase.Describe(json.RawMessage(`{"id":2}`)) == "" {
		t.Fatal("delete_knowledge_base should describe confirmation text")
	}
	out, err = reg.Execute(context.Background(), "delete_knowledge_base", json.RawMessage(`{"id":2}`))
	if err != nil {
		t.Fatalf("delete base: %v", err)
	}
	if !strings.Contains(out, `"deleted":true`) {
		t.Fatalf("unexpected delete base output: %s", out)
	}
}

func TestChatSystemPromptMentionsKnowledgeRules(t *testing.T) {
	for _, phrase := range []string{"search_knowledge", "do not use the knowledge base", "specific knowledge base"} {
		if !strings.Contains(ChatSystemPrompt, phrase) {
			t.Fatalf("system prompt should contain %q, got %s", phrase, ChatSystemPrompt)
		}
	}
}
