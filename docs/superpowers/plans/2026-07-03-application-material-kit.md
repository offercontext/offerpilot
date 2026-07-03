# Application Material Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build saved, editable application material kits that turn an application, JD, and selected resume into resume advice, outreach copy, and a completion checklist.

**Architecture:** Add a small SQLite-backed `application_material_kits` domain with CRUD methods, HTTP handlers, and one AI generation path. The frontend adds typed services and a full-width Drawer launched from `ApplicationDetail`, then wires incomplete kits into the existing action-item derivation.

**Tech Stack:** Go 1.22, SQLite via `modernc.org/sqlite`, chi HTTP routes, existing OpenAI-compatible AI client, React 18, TypeScript, Ant Design, React Query, Vitest.

---

## File Structure

- Create `internal/db/material_kits.go`: `ApplicationMaterialKit` model plus create/get/update helpers.
- Create `internal/db/material_kits_test.go`: database migration, uniqueness, and update tests.
- Create `internal/ai/material_kit.go`: prompt orchestration, JSON parsing, and marshal helpers for material kit generation.
- Create `internal/ai/material_kit_test.go`: prompt/JSON parsing tests that do not call a real model.
- Create `internal/api/material_kits.go`: REST handlers for get, generate, and update.
- Create `internal/api/material_kits_test.go`: API validation and persistence tests.
- Modify `internal/db/db.go`: add migration and indexes.
- Modify `internal/api/router.go`: register material kit routes.
- Create `web/src/types/materialKit.ts`: TypeScript model and request types.
- Create `web/src/services/materialKits.ts`: typed axios calls.
- Create `web/src/components/MaterialKitDrawer.tsx`: full-width editable Drawer.
- Create `web/src/components/MaterialKitDrawer.module.css`: focused layout styles.
- Modify `web/src/components/ApplicationDetail.tsx`: add entry button and Drawer state.
- Modify `web/src/lib/actionItems.ts`: add incomplete-kit action type and input.
- Modify `web/src/lib/actionItems.test.ts`: add material kit action coverage.

## Task 1: Database Model And Persistence

**Files:**
- Create: `internal/db/material_kits.go`
- Create: `internal/db/material_kits_test.go`
- Modify: `internal/db/db.go`

- [ ] **Step 1: Write failing database tests**

Create `internal/db/material_kits_test.go`:

```go
package db

import (
	"database/sql"
	"testing"
)

func TestApplicationMaterialKitCRUD(t *testing.T) {
	d, err := Init(t.TempDir() + "/kits.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	app := &Application{CompanyName: "Acme", PositionName: "Backend", Status: "applied", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create application: %v", err)
	}
	resume := &Resume{Name: "Backend Resume", ParsedData: "Go services", ParseStatus: "text-ready"}
	if err := d.CreateResume(resume); err != nil {
		t.Fatalf("create resume: %v", err)
	}

	kit := &ApplicationMaterialKit{
		ApplicationID: app.ID,
		ResumeID:      &resume.ID,
		Status:        "draft",
		JDSnapshot:    "Go backend JD",
		ContentJSON:   `{"checklist":[{"id":"select_resume","label":"Select resume","done":true}]}`,
	}
	if err := d.CreateApplicationMaterialKit(kit); err != nil {
		t.Fatalf("create kit: %v", err)
	}
	if kit.ID == 0 {
		t.Fatalf("expected kit id")
	}

	got, err := d.GetApplicationMaterialKitByApplication(app.ID)
	if err != nil {
		t.Fatalf("get kit: %v", err)
	}
	if got.ApplicationID != app.ID || got.ResumeID == nil || *got.ResumeID != resume.ID {
		t.Fatalf("unexpected kit: %+v", got)
	}

	got.Status = "ready"
	got.ContentJSON = `{"checklist":[{"id":"select_resume","label":"Select resume","done":true}],"resume_advice":{"summary":"ready"}}`
	if err := d.UpdateApplicationMaterialKit(got); err != nil {
		t.Fatalf("update kit: %v", err)
	}
	updated, err := d.GetApplicationMaterialKit(got.ID)
	if err != nil {
		t.Fatalf("get updated kit: %v", err)
	}
	if updated.Status != "ready" || updated.ContentJSON != got.ContentJSON {
		t.Fatalf("unexpected updated kit: %+v", updated)
	}
}

func TestApplicationMaterialKitUniquePerApplication(t *testing.T) {
	d, err := Init(t.TempDir() + "/kits_unique.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	app := &Application{CompanyName: "Acme", PositionName: "Backend", Status: "applied", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create application: %v", err)
	}

	first := &ApplicationMaterialKit{ApplicationID: app.ID, Status: "draft", ContentJSON: `{}`}
	second := &ApplicationMaterialKit{ApplicationID: app.ID, Status: "draft", ContentJSON: `{}`}
	if err := d.CreateApplicationMaterialKit(first); err != nil {
		t.Fatalf("create first: %v", err)
	}
	if err := d.CreateApplicationMaterialKit(second); err == nil {
		t.Fatalf("expected unique constraint error")
	}
}

func TestGetApplicationMaterialKitMissingReturnsNoRows(t *testing.T) {
	d, err := Init(t.TempDir() + "/kits_missing.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	if _, err := d.GetApplicationMaterialKitByApplication(999); err != sql.ErrNoRows {
		t.Fatalf("expected sql.ErrNoRows, got %v", err)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test ./internal/db -run MaterialKit -count=1`

Expected: FAIL with undefined `ApplicationMaterialKit` and missing database methods.

- [ ] **Step 3: Add model and persistence methods**

Create `internal/db/material_kits.go`:

```go
package db

import (
	"database/sql"
	"time"
)

// ApplicationMaterialKit stores editable generated material for one application.
type ApplicationMaterialKit struct {
	ID            int64     `json:"id"`
	ApplicationID int64     `json:"application_id"`
	ResumeID      *int64    `json:"resume_id,omitempty"`
	JDAnalysisID  *int64    `json:"jd_analysis_id,omitempty"`
	JDSnapshot    string    `json:"jd_snapshot"`
	Status        string    `json:"status"`       // draft | ready | submitted
	ContentJSON   string    `json:"content_json"` // JSON payload edited by the frontend
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

func (db *Database) CreateApplicationMaterialKit(k *ApplicationMaterialKit) error {
	if k.Status == "" {
		k.Status = "draft"
	}
	res, err := db.conn.Exec(
		`INSERT INTO application_material_kits
			(application_id, resume_id, jd_analysis_id, jd_snapshot, status, content_json)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		k.ApplicationID,
		nullableInt64(k.ResumeID),
		nullableInt64(k.JDAnalysisID),
		k.JDSnapshot,
		k.Status,
		k.ContentJSON,
	)
	if err != nil {
		return err
	}
	k.ID, _ = res.LastInsertId()
	now := time.Now()
	k.CreatedAt = now
	k.UpdatedAt = now
	return nil
}

func (db *Database) GetApplicationMaterialKit(id int64) (*ApplicationMaterialKit, error) {
	row := db.conn.QueryRow(
		`SELECT id, application_id, resume_id, jd_analysis_id, jd_snapshot, status, content_json, created_at, updated_at
		   FROM application_material_kits
		  WHERE id = ?`,
		id,
	)
	return scanApplicationMaterialKit(row)
}

func (db *Database) GetApplicationMaterialKitByApplication(applicationID int64) (*ApplicationMaterialKit, error) {
	row := db.conn.QueryRow(
		`SELECT id, application_id, resume_id, jd_analysis_id, jd_snapshot, status, content_json, created_at, updated_at
		   FROM application_material_kits
		  WHERE application_id = ?`,
		applicationID,
	)
	return scanApplicationMaterialKit(row)
}

func (db *Database) UpdateApplicationMaterialKit(k *ApplicationMaterialKit) error {
	res, err := db.conn.Exec(
		`UPDATE application_material_kits
		    SET resume_id = ?, jd_analysis_id = ?, jd_snapshot = ?, status = ?, content_json = ?, updated_at = ?
		  WHERE id = ?`,
		nullableInt64(k.ResumeID),
		nullableInt64(k.JDAnalysisID),
		k.JDSnapshot,
		k.Status,
		k.ContentJSON,
		time.Now(),
		k.ID,
	)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return sql.ErrNoRows
	}
	return nil
}

type rowScanner interface {
	Scan(dest ...interface{}) error
}

func scanApplicationMaterialKit(row rowScanner) (*ApplicationMaterialKit, error) {
	var k ApplicationMaterialKit
	var resumeID sql.NullInt64
	var jdAnalysisID sql.NullInt64
	if err := row.Scan(
		&k.ID,
		&k.ApplicationID,
		&resumeID,
		&jdAnalysisID,
		&k.JDSnapshot,
		&k.Status,
		&k.ContentJSON,
		&k.CreatedAt,
		&k.UpdatedAt,
	); err != nil {
		return nil, err
	}
	if resumeID.Valid {
		v := resumeID.Int64
		k.ResumeID = &v
	}
	if jdAnalysisID.Valid {
		v := jdAnalysisID.Int64
		k.JDAnalysisID = &v
	}
	return &k, nil
}
```

- [ ] **Step 4: Add migration**

In `internal/db/db.go`, add this migration before indexes:

```go
`CREATE TABLE IF NOT EXISTS application_material_kits (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	application_id INTEGER NOT NULL UNIQUE,
	resume_id INTEGER,
	jd_analysis_id INTEGER,
	jd_snapshot TEXT DEFAULT '',
	status TEXT NOT NULL DEFAULT 'draft',
	content_json TEXT NOT NULL DEFAULT '{}',
	created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
	FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
	FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE SET NULL,
	FOREIGN KEY (jd_analysis_id) REFERENCES jd_analyses(id) ON DELETE SET NULL
)`,
`CREATE INDEX IF NOT EXISTS idx_material_kits_app ON application_material_kits(application_id)`,
`CREATE INDEX IF NOT EXISTS idx_material_kits_status ON application_material_kits(status)`,
```

- [ ] **Step 5: Run database tests**

Run: `go test ./internal/db -run MaterialKit -count=1`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/db/db.go internal/db/material_kits.go internal/db/material_kits_test.go
git commit -m "feat: AI add material kit storage"
```

## Task 2: AI Generation And HTTP API

**Files:**
- Create: `internal/ai/material_kit.go`
- Create: `internal/ai/material_kit_test.go`
- Create: `internal/api/material_kits.go`
- Create: `internal/api/material_kits_test.go`
- Modify: `internal/api/router.go`

- [ ] **Step 1: Write AI parsing tests**

Create `internal/ai/material_kit_test.go`:

```go
package ai

import "testing"

func TestParseMaterialKitResult(t *testing.T) {
	raw := `{
		"resume_advice":{"summary":"Strong Go fit","highlights":["Go"],"rewrite_bullets":["Built APIs"],"gaps":["Kubernetes"],"notes":""},
		"messages":[{"type":"recruiter_email","title":"Intro","body":"Hello","notes":""}],
		"checklist":[{"id":"select_resume","label":"Select resume","done":true}]
	}`
	got, err := ParseMaterialKitResult(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if got.ResumeAdvice.Summary != "Strong Go fit" {
		t.Fatalf("unexpected summary: %+v", got.ResumeAdvice)
	}
	if len(got.Messages) != 1 || got.Messages[0].Type != "recruiter_email" {
		t.Fatalf("unexpected messages: %+v", got.Messages)
	}
	if len(got.Checklist) != 1 || !got.Checklist[0].Done {
		t.Fatalf("unexpected checklist: %+v", got.Checklist)
	}
}

func TestParseMaterialKitResultRejectsMissingChecklist(t *testing.T) {
	if _, err := ParseMaterialKitResult(`{"resume_advice":{"summary":"x"}}`); err == nil {
		t.Fatalf("expected error")
	}
}
```

- [ ] **Step 2: Run AI tests to verify they fail**

Run: `go test ./internal/ai -run MaterialKit -count=1`

Expected: FAIL with undefined material kit types/functions.

- [ ] **Step 3: Implement AI result types and prompt wrapper**

Create `internal/ai/material_kit.go`:

```go
package ai

import (
	"context"
	"encoding/json"
	"fmt"
)

type MaterialKitResult struct {
	ResumeAdvice MaterialKitResumeAdvice `json:"resume_advice"`
	Messages     []MaterialKitMessage    `json:"messages"`
	Checklist    []MaterialKitChecklist   `json:"checklist"`
}

type MaterialKitResumeAdvice struct {
	Summary        string   `json:"summary"`
	Highlights    []string `json:"highlights"`
	RewriteBullets []string `json:"rewrite_bullets"`
	Gaps           []string `json:"gaps"`
	Notes          string   `json:"notes"`
}

type MaterialKitMessage struct {
	Type  string `json:"type"`
	Title string `json:"title"`
	Body  string `json:"body"`
	Notes string `json:"notes"`
}

type MaterialKitChecklist struct {
	ID    string `json:"id"`
	Label string `json:"label"`
	Done  bool   `json:"done"`
}

func GenerateMaterialKit(ctx context.Context, c *Client, company, position, resumeText, jdText string) (*MaterialKitResult, error) {
	if resumeText == "" {
		return nil, fmt.Errorf("resume text is empty")
	}
	if jdText == "" {
		return nil, fmt.Errorf("JD text is empty")
	}
	system := "You are a career application materials assistant. Return only valid JSON matching the requested schema."
	user := fmt.Sprintf(`Create an application material kit for:
Company: %s
Position: %s

Resume:
%s

Job description:
%s

Return JSON with:
{
  "resume_advice": {"summary": string, "highlights": string[], "rewrite_bullets": string[], "gaps": string[], "notes": ""},
  "messages": [{"type": "recruiter_email"|"referral_message"|"application_note", "title": string, "body": string, "notes": ""}],
  "checklist": [{"id": string, "label": string, "done": boolean}]
}
Checklist must include select_resume, tailor_resume, prepare_message, submit_application, set_followup.`, company, position, truncateForPrompt(resumeText), truncateForPrompt(jdText))
	reply, err := c.Chat(ctx, system, user)
	if err != nil {
		return nil, err
	}
	return ParseMaterialKitResult(reply)
}

func ParseMaterialKitResult(raw string) (*MaterialKitResult, error) {
	var result MaterialKitResult
	if err := unmarshalJSONReply(raw, &result); err != nil {
		return nil, fmt.Errorf("parse AI material kit: %w (raw: %s)", err, truncate(raw, 200))
	}
	if result.ResumeAdvice.Summary == "" {
		return nil, fmt.Errorf("parse AI material kit: resume_advice.summary is required")
	}
	if len(result.Messages) == 0 {
		return nil, fmt.Errorf("parse AI material kit: at least one message is required")
	}
	if len(result.Checklist) == 0 {
		return nil, fmt.Errorf("parse AI material kit: checklist is required")
	}
	return &result, nil
}

func MarshalMaterialKit(result *MaterialKitResult) string {
	b, _ := json.Marshal(result)
	return string(b)
}
```

- [ ] **Step 4: Write API tests**

Create `internal/api/material_kits_test.go`:

```go
package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func materialKitTestDB(t *testing.T) (*db.Database, http.Handler) {
	t.Helper()
	dir := t.TempDir()
	d, err := db.Init(dir + "/material_kit_api.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d, NewRouter(d, dir)
}

func TestGetApplicationMaterialKitMissing(t *testing.T) {
	d, router := materialKitTestDB(t)
	app := &db.Application{CompanyName: "Acme", PositionName: "Backend", Status: "applied", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/applications/"+strconv.FormatInt(app.ID, 10)+"/material-kit", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d: %s", rec.Code, rec.Body.String())
	}
}

func TestUpdateApplicationMaterialKit(t *testing.T) {
	d, router := materialKitTestDB(t)
	app := &db.Application{CompanyName: "Acme", PositionName: "Backend", Status: "applied", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	kit := &db.ApplicationMaterialKit{ApplicationID: app.ID, Status: "draft", ContentJSON: `{"checklist":[]}`}
	if err := d.CreateApplicationMaterialKit(kit); err != nil {
		t.Fatalf("create kit: %v", err)
	}

	body := bytes.NewReader([]byte(`{"status":"ready","content_json":{"checklist":[{"id":"x","label":"X","done":true}]}}`))
	req := httptest.NewRequest(http.MethodPut, "/api/material-kits/"+strconv.FormatInt(kit.ID, 10), body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var got db.ApplicationMaterialKit
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got.Status != "ready" || !strings.Contains(got.ContentJSON, `"done":true`) {
		t.Fatalf("unexpected kit: %+v", got)
	}
}

func TestGenerateMaterialKitRequiresResume(t *testing.T) {
	d, router := materialKitTestDB(t)
	app := &db.Application{CompanyName: "Acme", PositionName: "Backend", Status: "applied", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	body := bytes.NewReader([]byte(`{"jd_text":"Go backend JD"}`))
	req := httptest.NewRequest(http.MethodPost, "/api/applications/"+strconv.FormatInt(app.ID, 10)+"/material-kit/generate", body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", rec.Code, rec.Body.String())
	}
}
```

- [ ] **Step 5: Implement handlers and routes**

Create `internal/api/material_kits.go`:

```go
package api

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

type generateMaterialKitRequest struct {
	ResumeID     int64  `json:"resume_id"`
	JDText       string `json:"jd_text"`
	JDAnalysisID *int64 `json:"jd_analysis_id,omitempty"`
	Overwrite    bool   `json:"overwrite"`
}

type updateMaterialKitRequest struct {
	ResumeID    *int64          `json:"resume_id,omitempty"`
	JDAnalysisID *int64         `json:"jd_analysis_id,omitempty"`
	JDSnapshot  string          `json:"jd_snapshot"`
	Status      string          `json:"status"`
	ContentJSON json.RawMessage `json:"content_json"`
}

func registerMaterialKitRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Get("/applications/{id}/material-kit", getApplicationMaterialKitHandler(database))
	r.Post("/applications/{id}/material-kit/generate", generateApplicationMaterialKitHandler(database, dataDir))
	r.Put("/material-kits/{id}", updateMaterialKitHandler(database))
}

func getApplicationMaterialKitHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, ok := int64URLParam(w, r, "id")
		if !ok {
			return
		}
		kit, err := database.GetApplicationMaterialKitByApplication(appID)
		if err == sql.ErrNoRows {
			respondError(w, http.StatusNotFound, "material kit not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, kit)
	}
}

func updateMaterialKitHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := int64URLParam(w, r, "id")
		if !ok {
			return
		}
		var req updateMaterialKitRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		if req.Status == "" {
			req.Status = "draft"
		}
		if !json.Valid(req.ContentJSON) {
			respondError(w, http.StatusBadRequest, "content_json must be valid JSON")
			return
		}
		kit, err := database.GetApplicationMaterialKit(id)
		if err == sql.ErrNoRows {
			respondError(w, http.StatusNotFound, "material kit not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		kit.ResumeID = req.ResumeID
		kit.JDAnalysisID = req.JDAnalysisID
		kit.JDSnapshot = req.JDSnapshot
		kit.Status = req.Status
		kit.ContentJSON = string(req.ContentJSON)
		if err := database.UpdateApplicationMaterialKit(kit); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		updated, _ := database.GetApplicationMaterialKit(id)
		respondJSON(w, http.StatusOK, updated)
	}
}

func generateApplicationMaterialKitHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, ok := int64URLParam(w, r, "id")
		if !ok {
			return
		}
		var req generateMaterialKitRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		if req.ResumeID <= 0 {
			respondError(w, http.StatusBadRequest, "resume_id is required")
			return
		}
		if req.JDText == "" {
			respondError(w, http.StatusBadRequest, "jd_text is required")
			return
		}
		if existing, err := database.GetApplicationMaterialKitByApplication(appID); err == nil && !req.Overwrite {
			respondJSON(w, http.StatusConflict, existing)
			return
		}

		app, err := database.GetApplication(appID)
		if err != nil {
			respondError(w, http.StatusNotFound, "application not found")
			return
		}
		resume, err := database.GetResume(req.ResumeID)
		if err != nil {
			respondError(w, http.StatusNotFound, "resume not found")
			return
		}
		if resume.ParsedData == "" {
			respondError(w, http.StatusBadRequest, "resume has no text content")
			return
		}
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
		result, err := ai.GenerateMaterialKit(r.Context(), client, app.CompanyName, app.PositionName, resume.ParsedData, req.JDText)
		if err != nil {
			respondError(w, http.StatusBadGateway, err.Error())
			return
		}
		content := ai.MarshalMaterialKit(result)
		kit := &db.ApplicationMaterialKit{
			ApplicationID: appID,
			ResumeID:      &req.ResumeID,
			JDAnalysisID:  req.JDAnalysisID,
			JDSnapshot:    req.JDText,
			Status:        "draft",
			ContentJSON:   content,
		}
		if existing, err := database.GetApplicationMaterialKitByApplication(appID); err == nil {
			kit.ID = existing.ID
			if err := database.UpdateApplicationMaterialKit(kit); err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
		} else if err := database.CreateApplicationMaterialKit(kit); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, kit)
	}
}

func int64URLParam(w http.ResponseWriter, r *http.Request, name string) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, name), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}
```

Modify `internal/api/router.go` inside `/api` routes after resume routes:

```go
// Application material kits (AI)
registerMaterialKitRoutes(r, database, dataDir)
```

- [ ] **Step 6: Run backend tests**

Run: `go test ./internal/ai ./internal/api -run 'MaterialKit|GenerateMaterialKit|ParseMaterialKit' -count=1`

Expected: PASS. `TestGenerateMaterialKitRequiresResume` passes without an API key because validation stops first.

- [ ] **Step 7: Commit**

```bash
git add internal/ai/material_kit.go internal/ai/material_kit_test.go internal/api/material_kits.go internal/api/material_kits_test.go internal/api/router.go
git commit -m "feat: AI add material kit API"
```

## Task 3: Frontend Types And Service Layer

**Files:**
- Create: `web/src/types/materialKit.ts`
- Create: `web/src/services/materialKits.ts`

- [ ] **Step 1: Create frontend material kit types**

Create `web/src/types/materialKit.ts`:

```ts
export type MaterialKitStatus = 'draft' | 'ready' | 'submitted';

export interface MaterialKitResumeAdvice {
  summary: string;
  highlights: string[];
  rewrite_bullets: string[];
  gaps: string[];
  notes: string;
}

export interface MaterialKitMessage {
  type: 'recruiter_email' | 'referral_message' | 'application_note' | string;
  title: string;
  body: string;
  notes: string;
}

export interface MaterialKitChecklistItem {
  id: string;
  label: string;
  done: boolean;
}

export interface MaterialKitContent {
  resume_advice: MaterialKitResumeAdvice;
  messages: MaterialKitMessage[];
  checklist: MaterialKitChecklistItem[];
}

export interface ApplicationMaterialKit {
  id: number;
  application_id: number;
  resume_id?: number;
  jd_analysis_id?: number;
  jd_snapshot: string;
  status: MaterialKitStatus;
  content_json: string;
  created_at: string;
  updated_at: string;
}

export interface MaterialKitViewModel extends Omit<ApplicationMaterialKit, 'content_json'> {
  content: MaterialKitContent;
}

export interface GenerateMaterialKitInput {
  resume_id: number;
  jd_text: string;
  jd_analysis_id?: number;
  overwrite?: boolean;
}

export interface UpdateMaterialKitInput {
  resume_id?: number;
  jd_analysis_id?: number;
  jd_snapshot: string;
  status: MaterialKitStatus;
  content_json: MaterialKitContent;
}
```

- [ ] **Step 2: Create service helpers with JSON parsing**

Create `web/src/services/materialKits.ts`:

```ts
import axios from 'axios';
import type {
  ApplicationMaterialKit,
  GenerateMaterialKitInput,
  MaterialKitContent,
  MaterialKitViewModel,
  UpdateMaterialKitInput,
} from '@/types/materialKit';

const http = axios.create({ baseURL: '/api', timeout: 130000 });

const emptyContent: MaterialKitContent = {
  resume_advice: { summary: '', highlights: [], rewrite_bullets: [], gaps: [], notes: '' },
  messages: [],
  checklist: [],
};

export function parseMaterialKit(raw: ApplicationMaterialKit): MaterialKitViewModel {
  let content: MaterialKitContent = emptyContent;
  try {
    content = { ...emptyContent, ...JSON.parse(raw.content_json || '{}') };
  } catch {
    content = emptyContent;
  }
  return { ...raw, content };
}

export async function getApplicationMaterialKit(applicationID: number): Promise<MaterialKitViewModel | null> {
  try {
    const { data } = await http.get<ApplicationMaterialKit>(`/applications/${applicationID}/material-kit`);
    return parseMaterialKit(data);
  } catch (error: any) {
    if (error?.response?.status === 404) return null;
    throw error;
  }
}

export async function generateApplicationMaterialKit(
  applicationID: number,
  input: GenerateMaterialKitInput,
): Promise<MaterialKitViewModel> {
  const { data } = await http.post<ApplicationMaterialKit>(
    `/applications/${applicationID}/material-kit/generate`,
    input,
  );
  return parseMaterialKit(data);
}

export async function updateMaterialKit(
  kitID: number,
  input: UpdateMaterialKitInput,
): Promise<MaterialKitViewModel> {
  const { data } = await http.put<ApplicationMaterialKit>(`/material-kits/${kitID}`, {
    ...input,
    content_json: input.content_json,
  });
  return parseMaterialKit(data);
}
```

- [ ] **Step 3: Run TypeScript build**

Run: `npm.cmd run build`

Working directory: `web`

Expected: PASS. The bundle-size warning may still appear and is not caused by this task.

- [ ] **Step 4: Commit**

```bash
git add web/src/types/materialKit.ts web/src/services/materialKits.ts
git commit -m "feat: AI add material kit frontend services"
```

## Task 4: Material Kit Drawer UI

**Files:**
- Create: `web/src/components/MaterialKitDrawer.tsx`
- Create: `web/src/components/MaterialKitDrawer.module.css`

- [ ] **Step 1: Implement Drawer component**

Create `web/src/components/MaterialKitDrawer.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Checkbox, Drawer, Empty, Input, Progress, Select, Space, Spin, Typography, message } from 'antd';
import { CopyOutlined, RobotOutlined, SaveOutlined } from '@ant-design/icons';
import type { Application } from '@/types/application';
import type { Resume } from '@/types/resume';
import type { MaterialKitContent, MaterialKitStatus } from '@/types/materialKit';
import { listResumes } from '@/services/resumes';
import {
  generateApplicationMaterialKit,
  getApplicationMaterialKit,
  updateMaterialKit,
} from '@/services/materialKits';
import styles from './MaterialKitDrawer.module.css';

const { Text, Title } = Typography;

const defaultContent: MaterialKitContent = {
  resume_advice: { summary: '', highlights: [], rewrite_bullets: [], gaps: [], notes: '' },
  messages: [
    { type: 'recruiter_email', title: 'HR 邮件', body: '', notes: '' },
    { type: 'referral_message', title: '内推私信', body: '', notes: '' },
    { type: 'application_note', title: '投递备注', body: '', notes: '' },
  ],
  checklist: [
    { id: 'confirm_jd', label: '确认 JD 和岗位要求', done: false },
    { id: 'select_resume', label: '选择用于投递的简历', done: false },
    { id: 'tailor_resume', label: '完成简历优化建议', done: false },
    { id: 'prepare_message', label: '准备沟通话术', done: false },
    { id: 'submit_application', label: '完成投递', done: false },
    { id: 'set_followup', label: '设置跟进提醒', done: false },
  ],
};

interface Props {
  application: Application | null;
  open: boolean;
  onClose: () => void;
}

export default function MaterialKitDrawer({ application, open, onClose }: Props) {
  const queryClient = useQueryClient();
  const [resumeID, setResumeID] = useState<number | undefined>();
  const [jdText, setJdText] = useState('');
  const [status, setStatus] = useState<MaterialKitStatus>('draft');
  const [content, setContent] = useState<MaterialKitContent>(defaultContent);
  const [saveError, setSaveError] = useState('');

  const kitQuery = useQuery({
    queryKey: ['material-kit', application?.id],
    queryFn: () => getApplicationMaterialKit(application!.id),
    enabled: open && !!application,
  });

  const resumesQuery = useQuery({
    queryKey: ['resumes'],
    queryFn: listResumes,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    if (kitQuery.data) {
      setResumeID(kitQuery.data.resume_id);
      setJdText(kitQuery.data.jd_snapshot);
      setStatus(kitQuery.data.status);
      setContent(kitQuery.data.content);
      return;
    }
    setResumeID(undefined);
    setJdText(application?.notes || '');
    setStatus('draft');
    setContent(defaultContent);
  }, [application?.notes, kitQuery.data, open]);

  const completion = useMemo(() => {
    if (content.checklist.length === 0) return 0;
    const done = content.checklist.filter((item) => item.done).length;
    return Math.round((done / content.checklist.length) * 100);
  }, [content.checklist]);

  const generateMut = useMutation({
    mutationFn: () =>
      generateApplicationMaterialKit(application!.id, {
        resume_id: resumeID!,
        jd_text: jdText,
        overwrite: Boolean(kitQuery.data),
      }),
    onSuccess: (kit) => {
      setContent(kit.content);
      setStatus(kit.status);
      setResumeID(kit.resume_id);
      setJdText(kit.jd_snapshot);
      queryClient.invalidateQueries({ queryKey: ['material-kit', application?.id] });
      message.success('材料包已生成');
    },
    onError: (error: any) => setSaveError(error?.response?.data?.error ?? '材料包生成失败'),
  });

  const saveMut = useMutation({
    mutationFn: () =>
      updateMaterialKit(kitQuery.data!.id, {
        resume_id: resumeID,
        jd_snapshot: jdText,
        status,
        content_json: content,
      }),
    onSuccess: (kit) => {
      setContent(kit.content);
      queryClient.invalidateQueries({ queryKey: ['material-kit', application?.id] });
      message.success('材料包已保存');
      setSaveError('');
    },
    onError: (error: any) => setSaveError(error?.response?.data?.error ?? '保存失败，请重试'),
  });

  const resumes = resumesQuery.data ?? [];
  const canGenerate = Boolean(application && resumeID && jdText.trim());
  const canSave = Boolean(kitQuery.data);

  const updateAdviceList = (key: 'highlights' | 'rewrite_bullets' | 'gaps', value: string) => {
    setContent((current) => ({
      ...current,
      resume_advice: {
        ...current.resume_advice,
        [key]: value.split('\n').map((line) => line.trim()).filter(Boolean),
      },
    }));
  };

  return (
    <Drawer
      title={application ? `${application.company_name} · ${application.position_name} 材料包` : '材料包'}
      open={open}
      onClose={onClose}
      width="min(1120px, calc(100vw - 32px))"
      destroyOnClose
    >
      {!application ? null : (
        <div className={styles.layout}>
          <aside className={styles.contextPanel}>
            <Text type="secondary">当前投递</Text>
            <Title level={4}>{application.company_name}</Title>
            <Text>{application.position_name}</Text>

            <div className={styles.block}>
              <Text strong>选择简历</Text>
              <Select
                value={resumeID}
                onChange={setResumeID}
                options={resumes.map((resume: Resume) => ({
                  value: resume.id,
                  label: resume.name || `简历 #${resume.id}`,
                }))}
                loading={resumesQuery.isLoading}
                placeholder="选择用于生成材料包的简历"
                style={{ width: '100%' }}
              />
            </div>

            <div className={styles.block}>
              <Text strong>JD 文本</Text>
              <Input.TextArea rows={6} value={jdText} onChange={(event) => setJdText(event.target.value)} />
            </div>

            <div className={styles.block}>
              <Text strong>完成度</Text>
              <Progress percent={completion} className="op-tnum" />
            </div>

            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                type="primary"
                icon={<RobotOutlined />}
                loading={generateMut.isPending}
                disabled={!canGenerate}
                onClick={() => generateMut.mutate()}
                block
              >
                {kitQuery.data ? '重新生成材料包' : '生成材料包'}
              </Button>
              <Button
                icon={<SaveOutlined />}
                loading={saveMut.isPending}
                disabled={!canSave}
                onClick={() => saveMut.mutate()}
                block
              >
                保存修改
              </Button>
            </Space>
          </aside>

          <main className={styles.editor}>
            {saveError && <Alert type="error" message={saveError} showIcon />}
            {kitQuery.isLoading ? (
              <Spin />
            ) : !kitQuery.data ? (
              <Empty description="选择简历并粘贴 JD 后生成材料包" />
            ) : (
              <>
                <section className={styles.section}>
                  <Title level={4}>简历优化建议</Title>
                  <Input.TextArea
                    rows={3}
                    value={content.resume_advice.summary}
                    onChange={(event) =>
                      setContent((current) => ({
                        ...current,
                        resume_advice: { ...current.resume_advice, summary: event.target.value },
                      }))
                    }
                  />
                  <Input.TextArea
                    rows={4}
                    value={content.resume_advice.highlights.join('\n')}
                    onChange={(event) => updateAdviceList('highlights', event.target.value)}
                    placeholder="建议突出点，每行一条"
                  />
                  <Input.TextArea
                    rows={4}
                    value={content.resume_advice.rewrite_bullets.join('\n')}
                    onChange={(event) => updateAdviceList('rewrite_bullets', event.target.value)}
                    placeholder="可替换 bullet，每行一条"
                  />
                  <Input.TextArea
                    rows={3}
                    value={content.resume_advice.gaps.join('\n')}
                    onChange={(event) => updateAdviceList('gaps', event.target.value)}
                    placeholder="能力缺口，每行一条"
                  />
                </section>

                <section className={styles.section}>
                  <Title level={4}>沟通话术</Title>
                  {content.messages.map((item, index) => (
                    <div className={styles.messageBox} key={`${item.type}-${index}`}>
                      <Input
                        value={item.title}
                        onChange={(event) =>
                          setContent((current) => ({
                            ...current,
                            messages: current.messages.map((messageItem, messageIndex) =>
                              messageIndex === index ? { ...messageItem, title: event.target.value } : messageItem,
                            ),
                          }))
                        }
                      />
                      <Input.TextArea
                        rows={4}
                        value={item.body}
                        onChange={(event) =>
                          setContent((current) => ({
                            ...current,
                            messages: current.messages.map((messageItem, messageIndex) =>
                              messageIndex === index ? { ...messageItem, body: event.target.value } : messageItem,
                            ),
                          }))
                        }
                      />
                      <Button icon={<CopyOutlined />} onClick={() => navigator.clipboard.writeText(item.body)}>
                        复制
                      </Button>
                    </div>
                  ))}
                </section>

                <section className={styles.section}>
                  <Title level={4}>投递检查清单</Title>
                  {content.checklist.map((item, index) => (
                    <label className={styles.checkItem} key={item.id}>
                      <Checkbox
                        checked={item.done}
                        onChange={(event) =>
                          setContent((current) => ({
                            ...current,
                            checklist: current.checklist.map((checkItem, checkIndex) =>
                              checkIndex === index ? { ...checkItem, done: event.target.checked } : checkItem,
                            ),
                          }))
                        }
                      />
                      <span>{item.label}</span>
                    </label>
                  ))}
                </section>
              </>
            )}
          </main>
        </div>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 2: Add Drawer CSS**

Create `web/src/components/MaterialKitDrawer.module.css`:

```css
.layout {
  display: grid;
  grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
  gap: 20px;
  min-height: calc(100vh - 120px);
}

.contextPanel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-radius: 12px;
  background: var(--op-layout-bg);
}

.block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  background: var(--op-surface);
  box-shadow: var(--op-shadow-sm);
}

.messageBox {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: 10px;
  background: var(--op-layout-bg);
}

.checkItem {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
}

.checkItem:hover {
  background: var(--op-layout-bg);
}

@media (max-width: 760px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Run frontend build**

Run: `npm.cmd run build`

Working directory: `web`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/MaterialKitDrawer.tsx web/src/components/MaterialKitDrawer.module.css
git commit -m "feat: AI add material kit drawer"
```

## Task 5: Application Detail Entry Point

**Files:**
- Modify: `web/src/components/ApplicationDetail.tsx`

- [ ] **Step 1: Add Drawer state and button**

In `web/src/components/ApplicationDetail.tsx`, add import:

```tsx
import { FileTextOutlined } from '@ant-design/icons';
import MaterialKitDrawer from './MaterialKitDrawer';
```

If combining icon imports, keep existing imports and include `FileTextOutlined`.

Inside component state, add:

```tsx
const [materialKitOpen, setMaterialKitOpen] = useState(false);
```

In the top action button area after the JD analysis button, add:

```tsx
<Button
  icon={<FileTextOutlined />}
  onClick={() => setMaterialKitOpen(true)}
  style={{ marginLeft: 8 }}
>
  材料包
</Button>
```

In `Drawer` `onClose`, also close nested material kit state:

```tsx
setMaterialKitOpen(false);
```

Before the closing fragment, render:

```tsx
<MaterialKitDrawer
  application={application}
  open={materialKitOpen}
  onClose={() => setMaterialKitOpen(false)}
/>
```

- [ ] **Step 2: Run frontend build**

Run: `npm.cmd run build`

Working directory: `web`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/ApplicationDetail.tsx
git commit -m "feat: AI add material kit entry"
```

## Task 6: Dashboard Action Item Integration

**Files:**
- Modify: `web/src/lib/actionItems.ts`
- Modify: `web/src/lib/actionItems.test.ts`
- Modify later if desired: `web/src/features/dashboard/DashboardView.tsx`, `web/src/features/reminders/RemindersView.tsx`

- [ ] **Step 1: Write failing action item test**

Add to `web/src/lib/actionItems.test.ts`:

```ts
it('creates material kit actions for active waiting applications without a completed kit', () => {
  const items = deriveActionItems({
    apps: [app({ id: 30, status: 'applied', company_name: 'Acme', position_name: 'Backend' })],
    events: [],
    offers: [],
    materialKits: [{ application_id: 30, complete: false }],
    practiceStats: stats({ due: 0 }),
    now,
  });

  expect(items).toContainEqual(
    expect.objectContaining({
      id: 'material-kit-30',
      kind: 'material_kit_incomplete',
      priority: 'p2',
      target: 'board',
      appId: 30,
      primaryActionLabel: '打开材料包',
    }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm.cmd test -- actionItems`

Working directory: `web`

Expected: FAIL because `materialKits` input and `material_kit_incomplete` kind do not exist.

- [ ] **Step 3: Extend action item types and derivation**

In `web/src/lib/actionItems.ts`:

Add kind:

```ts
| 'material_kit_incomplete'
```

Add input type:

```ts
interface MaterialKitActionState {
  application_id: number;
  complete: boolean;
}
```

Add field to `DeriveActionItemsInput`:

```ts
materialKits?: MaterialKitActionState[];
```

Update function signature destructuring:

```ts
materialKits = [],
```

Before `question_due`, add:

```ts
const materialKitByApp = new Map(materialKits.map((kit) => [kit.application_id, kit]));
for (const application of apps) {
  if (!WAITING_STATUSES.includes(application.status)) continue;
  const kit = materialKitByApp.get(application.id);
  if (kit?.complete) continue;
  items.push({
    id: `material-kit-${application.id}`,
    kind: 'material_kit_incomplete',
    priority: 'p2',
    title: `${application.company_name} · ${application.position_name} 投递材料包待完善`,
    detail: '简历建议、沟通话术或投递清单尚未完成。',
    primaryActionLabel: '打开材料包',
    target: 'board',
    appId: application.id,
    sortKey: 2200,
  });
}
```

Note: this task only extends pure derivation. Fetching material kit summaries for dashboard can be a follow-up because the current API returns one kit per app; do not add N+1 queries in `DashboardView` in this task.

- [ ] **Step 4: Run action item tests**

Run: `npm.cmd test -- actionItems`

Working directory: `web`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/actionItems.ts web/src/lib/actionItems.test.ts
git commit -m "feat: AI add material kit actions"
```

## Final Verification

- [ ] **Step 1: Run all Go tests**

Run: `go test ./...`

Expected: PASS.

- [ ] **Step 2: Run frontend tests**

Run: `npm.cmd test`

Working directory: `web`

Expected: PASS.

- [ ] **Step 3: Run frontend production build**

Run: `npm.cmd run build`

Working directory: `web`

Expected: PASS, with the pre-existing Vite chunk-size warning allowed.

- [ ] **Step 4: Review git status**

Run: `git status --short --branch`

Expected: clean branch after all task commits.

## Spec Coverage Review

- Product path and entry: Tasks 4 and 5.
- Database model: Task 1.
- Backend API: Task 2.
- AI generation boundary: Task 2.
- Frontend services and types: Task 3.
- Editable full-width Drawer: Task 4.
- Checklist state: Tasks 1, 2, 4, and 6.
- Dashboard action derivation: Task 6.
- MVP exclusions: preserved by keeping opportunity inbox, knowledge enhancement, versioning, and generic task system out of this plan.
