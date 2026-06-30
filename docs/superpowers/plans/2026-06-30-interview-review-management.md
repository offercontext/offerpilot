# Interview Review Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete interview review management workflow with a dedicated web view and AI chat create/query/update/delete support.

**Architecture:** Reuse the existing `interview_notes` SQLite table and `InterviewNote` model. Add one standalone note creation endpoint, expand frontend note services and views, and extend the AI tool registry while preserving the existing chat confirmation flow for writes.

**Tech Stack:** Go 1.22+, chi HTTP handlers, SQLite via `modernc.org/sqlite`, React 18, Ant Design 5, TanStack Query, TypeScript, Vite.

---

## File Structure

- Modify `internal/api/notes.go`: add `POST /api/notes`, share note-building/backfill validation between application-scoped and standalone creation, keep existing routes stable.
- Create `internal/api/notes_test.go`: handler tests for standalone creation, application backfill, update, and delete.
- Modify `internal/ai/tools.go`: expand `add_note`, add `update_note`, add `delete_note`, and preserve unspecified fields during AI updates.
- Modify `internal/ai/tools_test.go`: add registry tests for full note CRUD behavior and write flags.
- Modify `web/src/types/note.ts`: allow `application_id` in create/update payloads and add an update type alias.
- Modify `web/src/services/notes.ts`: add full list, standalone create, update, and delete functions.
- Create `web/src/components/ReviewFormDrawer.tsx`: shared drawer form for creating and editing reviews.
- Create `web/src/components/ReviewManagementView.tsx`: global reviews workspace with search, filters, list cards, create/edit/delete actions.
- Modify `web/src/App.tsx`: add the Reviews segmented view and render the new workspace.
- Modify `web/src/components/ApplicationDetail.tsx`: use shared edit-capable service behavior and keep quick per-application review entry.
- Modify `web/src/components/ChatPanel/index.tsx`: update suggested prompts with review-oriented examples.

---

### Task 1: Backend Standalone Note API

**Files:**
- Modify: `internal/api/notes.go`
- Create: `internal/api/notes_test.go`

- [ ] **Step 1: Add failing API tests**

Create `internal/api/notes_test.go`:

```go
package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

func noteTestDB(t *testing.T) (*db.Database, db.Application, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/notes.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	app := db.Application{
		CompanyName:  "ByteDance",
		PositionName: "Backend Engineer",
		Status:       "interview",
		Source:       "test",
		AppliedAt:    time.Date(2026, 6, 30, 10, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(&app); err != nil {
		t.Fatalf("create application: %v", err)
	}

	return d, app, NewRouter(d, t.TempDir())
}

func noteAPIRequest(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body: %v", err)
		}
		reader = bytes.NewReader(data)
	} else {
		reader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func TestNoteAPIStandaloneCreateAndCRUD(t *testing.T) {
	_, _, router := noteTestDB(t)

	createBody := map[string]interface{}{
		"company":           "Tencent",
		"position":          "Frontend Engineer",
		"round":             "Round 1",
		"date":              "2026-07-01",
		"questions":         "React performance",
		"self_reflection":   "Need clearer tradeoffs",
		"difficulty_points": "Virtual list",
		"mood":              "normal",
	}
	createRec := noteAPIRequest(t, router, http.MethodPost, "/api/notes", createBody)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", createRec.Code, createRec.Body.String())
	}
	var created db.InterviewNote
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created note: %v", err)
	}
	if created.Company != "Tencent" || created.Position != "Frontend Engineer" || created.DifficultyPoints != "Virtual list" {
		t.Fatalf("unexpected created note: %+v", created)
	}

	updateBody := map[string]interface{}{
		"company":           "Tencent",
		"position":          "Frontend Engineer",
		"round":             "Round 2",
		"date":              "2026-07-02",
		"questions":         "Project deep dive",
		"self_reflection":   "Answered with examples",
		"difficulty_points": "System design",
		"mood":              "good",
	}
	updateRec := noteAPIRequest(t, router, http.MethodPut, "/api/notes/"+strconv.FormatInt(created.ID, 10), updateBody)
	if updateRec.Code != http.StatusOK {
		t.Fatalf("update status %d: %s", updateRec.Code, updateRec.Body.String())
	}
	var updated db.InterviewNote
	if err := json.Unmarshal(updateRec.Body.Bytes(), &updated); err != nil {
		t.Fatalf("decode updated note: %v", err)
	}
	if updated.Round != "Round 2" || updated.Mood != "good" || updated.DifficultyPoints != "System design" {
		t.Fatalf("unexpected updated note: %+v", updated)
	}

	deleteRec := noteAPIRequest(t, router, http.MethodDelete, "/api/notes/"+strconv.FormatInt(created.ID, 10), nil)
	if deleteRec.Code != http.StatusOK {
		t.Fatalf("delete status %d: %s", deleteRec.Code, deleteRec.Body.String())
	}
	listRec := noteAPIRequest(t, router, http.MethodGet, "/api/notes", nil)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status %d: %s", listRec.Code, listRec.Body.String())
	}
	var listed []db.InterviewNote
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode listed notes: %v", err)
	}
	if len(listed) != 0 {
		t.Fatalf("expected deleted note to be absent, got %+v", listed)
	}
}

func TestNoteAPIStandaloneCreateBackfillsApplication(t *testing.T) {
	_, app, router := noteTestDB(t)

	createRec := noteAPIRequest(t, router, http.MethodPost, "/api/notes", map[string]interface{}{
		"application_id":    app.ID,
		"round":             "Round 1",
		"questions":         "Go scheduler",
		"self_reflection":   "Solid answer",
		"difficulty_points": "Runtime details",
	})
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", createRec.Code, createRec.Body.String())
	}
	var created db.InterviewNote
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created note: %v", err)
	}
	if created.ApplicationID == nil || *created.ApplicationID != app.ID {
		t.Fatalf("expected application link, got %+v", created)
	}
	if created.Company != app.CompanyName || created.Position != app.PositionName {
		t.Fatalf("expected backfilled company and position, got %+v", created)
	}
}

func TestNoteAPIStandaloneCreateValidation(t *testing.T) {
	_, app, router := noteTestDB(t)

	cases := []struct {
		name string
		body map[string]interface{}
	}{
		{name: "missing company", body: map[string]interface{}{"round": "Round 1"}},
		{name: "missing application and no company", body: map[string]interface{}{"application_id": app.ID + 999}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := noteAPIRequest(t, router, http.MethodPost, "/api/notes", tc.body)
			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400, got %d: %s", rec.Code, rec.Body.String())
			}
		})
	}
}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
go test ./internal/api -run TestNoteAPI -count=1
```

Expected: FAIL because `POST /api/notes` is not registered or returns method not allowed.

- [ ] **Step 3: Implement standalone create route and shared payload resolution**

In `internal/api/notes.go`, update `registerNoteRoutes` and add helper functions:

```go
func registerNoteRoutes(r chi.Router, database *db.Database) {
	r.Get("/applications/{id}/notes", listNotesByAppHandler(database))
	r.Post("/applications/{id}/notes", createNoteForAppHandler(database))
	r.Post("/notes", createStandaloneNoteHandler(database))
	r.Put("/notes/{id}", updateNoteHandler(database))
	r.Delete("/notes/{id}", deleteNoteHandler(database))
	r.Get("/notes", listNotesHandler(database))
}

func resolveNoteRequest(database *db.Database, req createNoteRequest, fallbackAppID *int64) (*db.InterviewNote, error) {
	appID := fallbackAppID
	if appID == nil && req.ApplicationID != nil {
		v := *req.ApplicationID
		appID = &v
	}
	if appID != nil && (req.Company == "" || req.Position == "") {
		app, err := database.GetApplication(*appID)
		if err == nil {
			if req.Company == "" {
				req.Company = app.CompanyName
			}
			if req.Position == "" {
				req.Position = app.PositionName
			}
		}
	}
	if req.Company == "" {
		return nil, errBadNoteCompany
	}
	return &db.InterviewNote{
		ApplicationID:    appID,
		Company:          req.Company,
		Position:         req.Position,
		Round:            req.Round,
		Date:             req.Date,
		Questions:        req.Questions,
		SelfReflection:   req.SelfReflection,
		DifficultyPoints: req.DifficultyPoints,
		Mood:             req.Mood,
	}, nil
}
```

Add imports:

```go
import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
)
```

Add package-level error:

```go
var errBadNoteCompany = errors.New("company is required")
```

Replace the body of `createNoteForAppHandler` after JSON decode with:

```go
n, err := resolveNoteRequest(database, req, &appID)
if err != nil {
	respondError(w, http.StatusBadRequest, err.Error())
	return
}
if err := database.CreateInterviewNote(n); err != nil {
	respondError(w, http.StatusInternalServerError, err.Error())
	return
}
respondJSON(w, http.StatusCreated, n)
```

Add new handler:

```go
func createStandaloneNoteHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req createNoteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		n, err := resolveNoteRequest(database, req, nil)
		if err != nil {
			respondError(w, http.StatusBadRequest, err.Error())
			return
		}
		if err := database.CreateInterviewNote(n); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, n)
	}
}
```

- [ ] **Step 4: Run note API tests**

Run:

```powershell
go test ./internal/api -run TestNoteAPI -count=1
```

Expected: PASS.

- [ ] **Step 5: Run full backend tests**

Run:

```powershell
go test ./...
```

Expected: PASS.

- [ ] **Step 6: Commit backend API work**

Run:

```powershell
git add internal/api/notes.go internal/api/notes_test.go
git commit -m "feat: AI add review note API"
```

---

### Task 2: AI Review Note Tools

**Files:**
- Modify: `internal/ai/tools.go`
- Modify: `internal/ai/tools_test.go`

- [ ] **Step 1: Add failing AI registry tests**

Append to `internal/ai/tools_test.go`:

```go
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
```

- [ ] **Step 2: Run AI tests to verify failure**

Run:

```powershell
go test ./internal/ai -run TestInterviewNoteTools -count=1
```

Expected: FAIL because `add_note` schema/handler is incomplete and `update_note`/`delete_note` do not exist.

- [ ] **Step 3: Add note tool helpers**

In `internal/ai/tools.go`, add helpers near the other tool helpers:

```go
func resolveToolNote(database *db.Database, appID *int64, company, position string) (*int64, string, string, error) {
	if appID != nil && (company == "" || position == "") {
		app, err := database.GetApplication(*appID)
		if err != nil {
			return appID, company, position, err
		}
		if company == "" {
			company = app.CompanyName
		}
		if position == "" {
			position = app.PositionName
		}
	}
	if company == "" {
		return appID, company, position, fmt.Errorf("company is required")
	}
	return appID, company, position, nil
}
```

- [ ] **Step 4: Expand `add_note` and add update/delete tools**

Replace the existing `add_note` registration with:

```go
r.add(Tool{
	Name:        "add_note",
	Description: "Add an interview review note. If application_id is provided, missing company and position are filled from the application.",
	Write:       true,
	Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"},"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"date":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"difficulty_points":{"type":"string"},"mood":{"type":"string"}}}`),
	Describe: func(args json.RawMessage) string {
		var p struct {
			Company       string `json:"company"`
			Position      string `json:"position"`
			ApplicationID *int64 `json:"application_id"`
			Round         string `json:"round"`
		}
		_ = json.Unmarshal(args, &p)
		if p.Company == "" && p.ApplicationID != nil {
			return fmt.Sprintf("Add interview review for application #%d (%s)", *p.ApplicationID, p.Round)
		}
		return fmt.Sprintf("Add interview review: %s - %s (%s)", p.Company, p.Position, p.Round)
	},
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		var p struct {
			ApplicationID    *int64 `json:"application_id"`
			Company          string `json:"company"`
			Position         string `json:"position"`
			Round            string `json:"round"`
			Date             string `json:"date"`
			Questions        string `json:"questions"`
			SelfReflection   string `json:"self_reflection"`
			DifficultyPoints string `json:"difficulty_points"`
			Mood             string `json:"mood"`
		}
		if err := json.Unmarshal(args, &p); err != nil {
			return "", err
		}
		appID, company, position, err := resolveToolNote(database, p.ApplicationID, p.Company, p.Position)
		if err != nil {
			return "", err
		}
		note := &db.InterviewNote{
			ApplicationID:    appID,
			Company:          company,
			Position:         position,
			Round:            p.Round,
			Date:             p.Date,
			Questions:        p.Questions,
			SelfReflection:   p.SelfReflection,
			DifficultyPoints: p.DifficultyPoints,
			Mood:             p.Mood,
		}
		if err := database.CreateInterviewNote(note); err != nil {
			return "", err
		}
		return jsonResult(note)
	},
})
```

Add these registrations after `add_note`:

```go
r.add(Tool{
	Name:        "update_note",
	Description: "Update an existing interview review note by id. Omitted fields keep their current values.",
	Write:       true,
	Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"application_id":{"type":"integer"},"company":{"type":"string"},"position":{"type":"string"},"round":{"type":"string"},"date":{"type":"string"},"questions":{"type":"string"},"self_reflection":{"type":"string"},"difficulty_points":{"type":"string"},"mood":{"type":"string"}},"required":["id"]}`),
	Describe: func(args json.RawMessage) string {
		var p struct {
			ID int64 `json:"id"`
		}
		_ = json.Unmarshal(args, &p)
		return fmt.Sprintf("Update interview review note #%d", p.ID)
	},
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		var p struct {
			ID               int64  `json:"id"`
			ApplicationID    *int64 `json:"application_id"`
			Company          string `json:"company"`
			Position         string `json:"position"`
			Round            string `json:"round"`
			Date             string `json:"date"`
			Questions        string `json:"questions"`
			SelfReflection   string `json:"self_reflection"`
			DifficultyPoints string `json:"difficulty_points"`
			Mood             string `json:"mood"`
		}
		if err := json.Unmarshal(args, &p); err != nil {
			return "", err
		}
		note, err := database.GetInterviewNote(p.ID)
		if err != nil {
			return "", err
		}
		if p.ApplicationID != nil {
			note.ApplicationID = p.ApplicationID
		}
		if p.Company != "" {
			note.Company = p.Company
		}
		if p.Position != "" {
			note.Position = p.Position
		}
		if p.Round != "" {
			note.Round = p.Round
		}
		if p.Date != "" {
			note.Date = p.Date
		}
		if p.Questions != "" {
			note.Questions = p.Questions
		}
		if p.SelfReflection != "" {
			note.SelfReflection = p.SelfReflection
		}
		if p.DifficultyPoints != "" {
			note.DifficultyPoints = p.DifficultyPoints
		}
		if p.Mood != "" {
			note.Mood = p.Mood
		}
		if err := database.UpdateInterviewNote(note); err != nil {
			return "", err
		}
		return jsonResult(note)
	},
})
r.add(Tool{
	Name:        "delete_note",
	Description: "Delete an interview review note by id.",
	Write:       true,
	Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
	Describe: func(args json.RawMessage) string {
		var p struct {
			ID int64 `json:"id"`
		}
		_ = json.Unmarshal(args, &p)
		return fmt.Sprintf("Delete interview review note #%d", p.ID)
	},
	Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
		var p struct {
			ID int64 `json:"id"`
		}
		if err := json.Unmarshal(args, &p); err != nil {
			return "", err
		}
		if _, err := database.GetInterviewNote(p.ID); err != nil {
			return "", err
		}
		if err := database.DeleteInterviewNote(p.ID); err != nil {
			return "", err
		}
		return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
	},
})
```

- [ ] **Step 5: Run AI tests**

Run:

```powershell
go test ./internal/ai -run TestInterviewNoteTools -count=1
```

Expected: PASS.

- [ ] **Step 6: Run backend tests**

Run:

```powershell
go test ./...
```

Expected: PASS.

- [ ] **Step 7: Commit AI tool work**

Run:

```powershell
git add internal/ai/tools.go internal/ai/tools_test.go
git commit -m "feat: AI manage interview reviews in chat"
```

---

### Task 3: Frontend Note Service and Shared Form

**Files:**
- Modify: `web/src/types/note.ts`
- Modify: `web/src/services/notes.ts`
- Create: `web/src/components/ReviewFormDrawer.tsx`

- [ ] **Step 1: Expand note types**

Modify `web/src/types/note.ts`:

```ts
export interface CreateNoteInput {
  application_id?: number;
  company?: string;
  position?: string;
  round?: string;
  date?: string;
  questions?: string;
  self_reflection?: string;
  difficulty_points?: string;
  mood?: string;
}

export type UpdateNoteInput = CreateNoteInput;
```

- [ ] **Step 2: Expand note service**

Modify `web/src/services/notes.ts`:

```ts
import axios from 'axios';
import type { CreateNoteInput, InterviewNote, UpdateNoteInput } from '@/types/note';

const http = axios.create({ baseURL: '/api', timeout: 10000 });

export async function listNotes(): Promise<InterviewNote[]> {
  const { data } = await http.get<InterviewNote[]>('/notes');
  return data;
}

export async function listNotesByApp(appID: number): Promise<InterviewNote[]> {
  const { data } = await http.get<InterviewNote[]>(`/applications/${appID}/notes`);
  return data;
}

export async function createNote(appID: number, input: CreateNoteInput): Promise<InterviewNote> {
  const { data } = await http.post<InterviewNote>(`/applications/${appID}/notes`, input);
  return data;
}

export async function createStandaloneNote(input: CreateNoteInput): Promise<InterviewNote> {
  const { data } = await http.post<InterviewNote>('/notes', input);
  return data;
}

export async function updateNote(id: number, input: UpdateNoteInput): Promise<InterviewNote> {
  const { data } = await http.put<InterviewNote>(`/notes/${id}`, input);
  return data;
}

export async function deleteNote(id: number): Promise<void> {
  await http.delete(`/notes/${id}`);
}
```

- [ ] **Step 3: Create shared drawer form**

Create `web/src/components/ReviewFormDrawer.tsx`:

```tsx
import { useEffect } from 'react';
import { Drawer, Form, Input, Select, Button, Space } from 'antd';
import type { Application } from '@/types/application';
import type { CreateNoteInput, InterviewNote } from '@/types/note';

const MOOD_OPTIONS = [
  { value: 'good', label: '好' },
  { value: 'normal', label: '一般' },
  { value: 'bad', label: '差' },
];

interface Props {
  open: boolean;
  applications: Application[];
  initialApplication?: Application | null;
  note?: InterviewNote | null;
  saving?: boolean;
  onSubmit: (input: CreateNoteInput) => void;
  onClose: () => void;
}

export default function ReviewFormDrawer({
  open,
  applications,
  initialApplication,
  note,
  saving = false,
  onSubmit,
  onClose,
}: Props) {
  const [form] = Form.useForm<CreateNoteInput>();
  const editing = !!note;

  useEffect(() => {
    if (!open) return;
    if (note) {
      form.setFieldsValue({
        application_id: note.application_id,
        company: note.company,
        position: note.position,
        round: note.round,
        date: note.date,
        questions: note.questions,
        self_reflection: note.self_reflection,
        difficulty_points: note.difficulty_points,
        mood: note.mood,
      });
      return;
    }
    form.resetFields();
    if (initialApplication) {
      form.setFieldsValue({
        application_id: initialApplication.id,
        company: initialApplication.company_name,
        position: initialApplication.position_name,
      });
    }
  }, [open, note, initialApplication, form]);

  function handleApplicationChange(appID?: number) {
    const app = applications.find((item) => item.id === appID);
    if (!app) return;
    form.setFieldsValue({
      company: app.company_name,
      position: app.position_name,
    });
  }

  return (
    <Drawer
      title={editing ? '编辑面试复盘' : '新建面试复盘'}
      open={open}
      onClose={onClose}
      width={520}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="application_id" label="关联投递">
          <Select
            allowClear
            showSearch
            placeholder="可选"
            optionFilterProp="label"
            onChange={handleApplicationChange}
            options={applications.map((app) => ({
              value: app.id,
              label: `${app.company_name} / ${app.position_name}`,
            }))}
          />
        </Form.Item>
        <Space style={{ width: '100%' }} align="start">
          <Form.Item name="company" label="公司" rules={[{ required: true, message: '请输入公司' }]} style={{ width: 240 }}>
            <Input placeholder="公司" />
          </Form.Item>
          <Form.Item name="position" label="岗位" style={{ width: 240 }}>
            <Input placeholder="岗位" />
          </Form.Item>
        </Space>
        <Space style={{ width: '100%' }} align="start">
          <Form.Item name="round" label="轮次" style={{ width: 160 }}>
            <Input placeholder="一面" />
          </Form.Item>
          <Form.Item name="date" label="日期" style={{ width: 160 }}>
            <Input placeholder="2026-07-01" />
          </Form.Item>
          <Form.Item name="mood" label="心情" style={{ width: 160 }}>
            <Select options={MOOD_OPTIONS} allowClear placeholder="选择" />
          </Form.Item>
        </Space>
        <Form.Item name="questions" label="面试问题">
          <Input.TextArea rows={4} placeholder="记录被问到的问题" />
        </Form.Item>
        <Form.Item name="self_reflection" label="自我反思">
          <Input.TextArea rows={4} placeholder="表现如何，哪里可以改进" />
        </Form.Item>
        <Form.Item name="difficulty_points" label="难点/薄弱点">
          <Input.TextArea rows={4} placeholder="哪些知识点没答好" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>
          保存复盘
        </Button>
      </Form>
    </Drawer>
  );
}
```

- [ ] **Step 4: Run frontend build**

Run:

```powershell
npm.cmd run build
```

from `web/`.

Expected: PASS.

- [ ] **Step 5: Commit service and form**

Run:

```powershell
git add web/src/types/note.ts web/src/services/notes.ts web/src/components/ReviewFormDrawer.tsx
git commit -m "feat: AI add review form foundation"
```

---

### Task 4: Dedicated Review Management View

**Files:**
- Create: `web/src/components/ReviewManagementView.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Create Reviews workspace**

Create `web/src/components/ReviewManagementView.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card, Empty, Input, Popconfirm, Select, Space, Spin, Tag, Typography, message } from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import type { Application } from '@/types/application';
import type { CreateNoteInput, InterviewNote } from '@/types/note';
import { createStandaloneNote, deleteNote, listNotes, updateNote } from '@/services/notes';
import ReviewFormDrawer from '@/components/ReviewFormDrawer';

const { Text, Paragraph } = Typography;

interface Props {
  applications: Application[];
}

function includesText(value: string | undefined, query: string) {
  return (value ?? '').toLowerCase().includes(query);
}

export default function ReviewManagementView({ applications }: Props) {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<InterviewNote | null>(null);
  const [search, setSearch] = useState('');
  const [applicationID, setApplicationID] = useState<number | undefined>();
  const [mood, setMood] = useState<string | undefined>();

  const notesQuery = useQuery({
    queryKey: ['notes', 'all'],
    queryFn: listNotes,
  });

  const invalidateNotes = () => queryClient.invalidateQueries({ queryKey: ['notes'] });

  const createMut = useMutation({
    mutationFn: createStandaloneNote,
    onSuccess: () => {
      message.success('已保存面试复盘');
      setDrawerOpen(false);
      invalidateNotes();
    },
    onError: () => message.error('保存失败'),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, input }: { id: number; input: CreateNoteInput }) => updateNote(id, input),
    onSuccess: () => {
      message.success('已更新面试复盘');
      setEditing(null);
      setDrawerOpen(false);
      invalidateNotes();
    },
    onError: () => message.error('更新失败'),
  });

  const deleteMut = useMutation({
    mutationFn: deleteNote,
    onSuccess: () => {
      message.success('已删除面试复盘');
      invalidateNotes();
    },
    onError: () => message.error('删除失败'),
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (notesQuery.data ?? []).filter((note) => {
      if (applicationID && note.application_id !== applicationID) return false;
      if (mood && note.mood !== mood) return false;
      if (!q) return true;
      return (
        includesText(note.company, q) ||
        includesText(note.position, q) ||
        includesText(note.round, q) ||
        includesText(note.questions, q) ||
        includesText(note.self_reflection, q) ||
        includesText(note.difficulty_points, q)
      );
    });
  }, [notesQuery.data, search, applicationID, mood]);

  function openCreate() {
    setEditing(null);
    setDrawerOpen(true);
  }

  function handleSubmit(input: CreateNoteInput) {
    if (editing) {
      updateMut.mutate({ id: editing.id, input });
    } else {
      createMut.mutate(input);
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', alignItems: 'center' }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建复盘
        </Button>
        <Input.Search
          allowClear
          placeholder="搜索公司、岗位、问题、反思"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        <Select
          allowClear
          showSearch
          placeholder="按投递筛选"
          optionFilterProp="label"
          value={applicationID}
          onChange={setApplicationID}
          style={{ width: 240 }}
          options={applications.map((app) => ({
            value: app.id,
            label: `${app.company_name} / ${app.position_name}`,
          }))}
        />
        <Select
          allowClear
          placeholder="按心情筛选"
          value={mood}
          onChange={setMood}
          style={{ width: 140 }}
          options={[
            { value: 'good', label: '好' },
            { value: 'normal', label: '一般' },
            { value: 'bad', label: '差' },
          ]}
        />
      </Space>

      {notesQuery.isLoading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <Empty description={notesQuery.data?.length ? '没有匹配的复盘' : '还没有面试复盘'} />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {filtered.map((note) => (
            <Card
              key={note.id}
              size="small"
              title={`${note.company} / ${note.position || '未填写岗位'} / ${note.round || '未标注轮次'}`}
              extra={
                <Space>
                  {note.date && <Text type="secondary">{note.date}</Text>}
                  {note.mood && <Tag color="green">{note.mood}</Tag>}
                  <Button type="text" icon={<EditOutlined />} onClick={() => { setEditing(note); setDrawerOpen(true); }} />
                  <Popconfirm title="删除这条复盘？" onConfirm={() => deleteMut.mutate(note.id)} okText="删除" cancelText="取消">
                    <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              }
            >
              {note.questions && <Paragraph ellipsis={{ rows: 2 }}>问题：{note.questions}</Paragraph>}
              {note.self_reflection && <Paragraph ellipsis={{ rows: 2 }}>反思：{note.self_reflection}</Paragraph>}
              {note.difficulty_points && <Paragraph ellipsis={{ rows: 2 }}>难点：{note.difficulty_points}</Paragraph>}
            </Card>
          ))}
        </Space>
      )}

      <ReviewFormDrawer
        open={drawerOpen}
        applications={applications}
        note={editing}
        saving={createMut.isPending || updateMut.isPending}
        onSubmit={handleSubmit}
        onClose={() => {
          setDrawerOpen(false);
          setEditing(null);
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Wire Reviews view into `App.tsx`**

Modify imports:

```tsx
import ReviewManagementView from '@/components/ReviewManagementView';
```

Change view state:

```tsx
const [viewMode, setViewMode] = useState<'board' | 'calendar' | 'reviews'>('board');
```

Change segmented options:

```tsx
<Segmented
  value={viewMode}
  onChange={(v) => setViewMode(v as 'board' | 'calendar' | 'reviews')}
  options={[
    { label: '看板', value: 'board' },
    { label: '日历', value: 'calendar' },
    { label: '复盘', value: 'reviews' },
  ]}
  style={{ marginBottom: 16 }}
/>
```

Change rendering branch:

```tsx
) : viewMode === 'board' ? (
  <KanbanBoard applications={applications} onOpenDetail={(app) => setSelected(app)} />
) : viewMode === 'calendar' ? (
  <CalendarView applications={applications} onOpenDetail={(app) => setSelected(app)} />
) : (
  <ReviewManagementView applications={applications} />
)}
```

- [ ] **Step 3: Run frontend build**

Run:

```powershell
npm.cmd run build
```

from `web/`.

Expected: PASS.

- [ ] **Step 4: Commit Reviews view**

Run:

```powershell
git add web/src/App.tsx web/src/components/ReviewManagementView.tsx
git commit -m "feat: AI add review management view"
```

---

### Task 5: Application Detail Review Refinement

**Files:**
- Modify: `web/src/components/ApplicationDetail.tsx`

- [ ] **Step 1: Add edit support and align note invalidation**

Modify imports:

```tsx
import { listNotesByApp, createNote, deleteNote as removeNote, updateNote } from '@/services/notes';
import ReviewFormDrawer from './ReviewFormDrawer';
import type { InterviewNote } from '@/types/note';
```

Add state:

```tsx
const [editingNote, setEditingNote] = useState<InterviewNote | null>(null);
```

Add mutation:

```tsx
const updateNoteMut = useMutation({
  mutationFn: ({ id, input }: { id: number; input: CreateNoteInput }) => updateNote(id, input),
  onSuccess: () => {
    message.success('已更新面试复盘');
    setEditingNote(null);
    invalidateNotes();
    queryClient.invalidateQueries({ queryKey: ['notes', 'all'] });
  },
  onError: () => message.error('更新失败'),
});
```

In existing add/delete `onSuccess`, also invalidate the global list:

```tsx
queryClient.invalidateQueries({ queryKey: ['notes', 'all'] });
```

Add an edit button next to delete in each timeline item:

```tsx
<Button type="text" size="small" onClick={() => setEditingNote(n)}>
  编辑
</Button>
```

Render shared drawer near the existing modals:

```tsx
<ReviewFormDrawer
  open={!!editingNote}
  applications={[application]}
  initialApplication={application}
  note={editingNote}
  saving={updateNoteMut.isPending}
  onSubmit={(input) => {
    if (editingNote) updateNoteMut.mutate({ id: editingNote.id, input });
  }}
  onClose={() => setEditingNote(null)}
/>
```

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm.cmd run build
```

from `web/`.

Expected: PASS.

- [ ] **Step 3: Commit detail refinement**

Run:

```powershell
git add web/src/components/ApplicationDetail.tsx
git commit -m "feat: AI refine application review editing"
```

---

### Task 6: Chat Prompt Updates and Final Verification

**Files:**
- Modify: `web/src/components/ChatPanel/index.tsx`

- [ ] **Step 1: Update suggested prompts**

Replace `SUGGESTED_PROMPTS` with:

```tsx
const SUGGESTED_PROMPTS = [
  '我现在有哪些投递记录？',
  '帮我记录刚才的面试复盘',
  '总结最近复盘里的薄弱点',
  '帮我看看最近有哪些笔试面试测评日程',
];
```

- [ ] **Step 2: Run full backend tests**

Run from repo root:

```powershell
go test ./...
```

Expected: PASS.

- [ ] **Step 3: Run frontend production build**

Run from `web/`:

```powershell
npm.cmd run build
```

Expected: PASS. The existing Vite chunk-size warning is acceptable unless a new build error appears.

- [ ] **Step 4: Inspect final git diff**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only intended source/test files are modified, plus ignored build/dependency artifacts are not staged.

- [ ] **Step 5: Commit final prompt and verification update**

Run:

```powershell
git add web/src/components/ChatPanel/index.tsx
git commit -m "feat: AI add review assistant prompts"
```

---

## Self-Review Notes

- Spec coverage: backend standalone creation is Task 1; AI CRUD is Task 2; frontend services and form are Task 3; independent Reviews view is Task 4; application detail lightweight entry is Task 5; final prompt and verification are Task 6.
- Database scope: no migration or model expansion is included.
- Confirmation flow: AI note write tools are marked `Write: true`, so existing chat confirmation behavior remains in place.
- Testing coverage: backend API and AI registry tests are explicit; frontend is verified through TypeScript/Vite build, matching current repo practice.
