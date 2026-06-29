# Schedule Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class schedule events for written tests, interviews, and assessments that can be created in the UI, shown on the calendar, and managed by the AI assistant.

**Architecture:** Complete the existing SQLite `events` table path instead of creating a parallel model. Backend DB/API layers expose event CRUD with duration as `duration_minutes`; calendar aggregation includes editable schedule entries. Frontend reuses one schedule form from calendar and application detail, while AI tools use the existing write-confirmation loop.

**Tech Stack:** Go 1.22, SQLite via `modernc.org/sqlite`, chi router, React 18, TypeScript, Ant Design, TanStack Query, dayjs, Vite.

---

## File Structure

- Create `internal/db/events.go`: event filter structs, event-with-application response type, validation helpers, and CRUD/query methods for the existing `events` table.
- Create `internal/db/events_test.go`: DB tests for create/get/list/update/delete, month/application filtering, and application cascade behavior.
- Create `internal/api/events.go`: HTTP request/response structs, route registration, API validation, duration conversion, and event handlers.
- Create `internal/api/events_test.go`: API tests for event CRUD and validation responses.
- Modify `internal/api/router.go`: register event routes under `/api`.
- Modify `internal/api/calendar.go`: merge schedule events into calendar entries and mark only those entries editable.
- Create or modify `internal/api/calendar_test.go`: verify calendar response includes formal events plus existing applied/note entries.
- Modify `internal/ai/tools.go`: add `list_events`, `get_event`, `create_event`, `update_event`, and `delete_event` tools.
- Modify `internal/ai/tools_test.go`: cover event tools and confirmation descriptions.
- Modify `internal/ai/summary.go`: include upcoming schedule events in read-only fallback summaries.
- Modify `web/src/types/calendar.ts`: extend calendar entry fields for schedule events.
- Create `web/src/types/event.ts`: frontend event types and event input types.
- Create `web/src/services/events.ts`: API client for event CRUD/list.
- Create `web/src/components/ScheduleEventForm.tsx`: shared drawer/form used by calendar and application detail.
- Modify `web/src/components/CalendarView.tsx`: add new-event entry point, show schedule chips, and support edit/delete for formal events.
- Modify `web/src/components/CalendarView.module.css`: styles for chips and event metadata.
- Modify `web/src/components/ApplicationDetail.tsx`: add an application-scoped schedule section and launch the shared form with the current application preselected.

---

### Task 1: Database Event Model

**Files:**
- Create: `internal/db/events.go`
- Test: `internal/db/events_test.go`

- [ ] **Step 1: Write failing DB tests**

Create `internal/db/events_test.go`:

```go
package db

import (
	"testing"
	"time"
)

func createEventTestApplication(t *testing.T, d *Database) Application {
	t.Helper()
	app := Application{
		CompanyName:  "字节",
		PositionName: "后端",
		Status:       "interview",
		Source:       "test",
		AppliedAt:    time.Date(2026, 6, 29, 10, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(&app); err != nil {
		t.Fatalf("create application: %v", err)
	}
	return app
}

func TestEventCRUDAndApplicationListing(t *testing.T) {
	d := newTestDB(t)
	app := createEventTestApplication(t, d)
	scheduled := time.Date(2026, 7, 3, 14, 0, 0, 0, time.UTC)

	event := &Event{
		ApplicationID: app.ID,
		EventType:     "interview",
		Round:         1,
		ScheduledAt:   &scheduled,
		Duration:      "60",
		Location:      "腾讯会议",
		Notes:         "准备项目经历",
	}
	if err := d.CreateEvent(event); err != nil {
		t.Fatalf("create event: %v", err)
	}
	if event.ID == 0 {
		t.Fatal("expected event id")
	}

	got, err := d.GetEvent(event.ID)
	if err != nil {
		t.Fatalf("get event: %v", err)
	}
	if got.EventType != "interview" || got.Duration != "60" || got.Location != "腾讯会议" {
		t.Fatalf("unexpected event: %+v", got)
	}

	items, err := d.ListEvents(EventFilter{ApplicationID: app.ID})
	if err != nil {
		t.Fatalf("list by application: %v", err)
	}
	if len(items) != 1 || items[0].CompanyName != "字节" || items[0].PositionName != "后端" {
		t.Fatalf("unexpected listed events: %+v", items)
	}

	got.Duration = "90"
	got.Location = "线下"
	if err := d.UpdateEvent(got); err != nil {
		t.Fatalf("update event: %v", err)
	}
	updated, _ := d.GetEvent(event.ID)
	if updated.Duration != "90" || updated.Location != "线下" {
		t.Fatalf("event was not updated: %+v", updated)
	}

	if err := d.DeleteEvent(event.ID); err != nil {
		t.Fatalf("delete event: %v", err)
	}
	after, err := d.ListEvents(EventFilter{ApplicationID: app.ID})
	if err != nil {
		t.Fatalf("list after delete: %v", err)
	}
	if len(after) != 0 {
		t.Fatalf("expected no events after delete, got %+v", after)
	}
}

func TestListEventsByMonthAndType(t *testing.T) {
	d := newTestDB(t)
	app := createEventTestApplication(t, d)
	july := time.Date(2026, 7, 3, 14, 0, 0, 0, time.UTC)
	august := time.Date(2026, 8, 1, 9, 0, 0, 0, time.UTC)
	events := []*Event{
		{ApplicationID: app.ID, EventType: "interview", ScheduledAt: &july, Duration: "60"},
		{ApplicationID: app.ID, EventType: "assessment", ScheduledAt: &august, Duration: "45"},
	}
	for _, event := range events {
		if err := d.CreateEvent(event); err != nil {
			t.Fatalf("create event: %v", err)
		}
	}

	items, err := d.ListEvents(EventFilter{Month: "2026-07", EventType: "interview"})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(items) != 1 || items[0].EventType != "interview" {
		t.Fatalf("unexpected July interview events: %+v", items)
	}
}

func TestApplicationDeleteCascadesEvents(t *testing.T) {
	d := newTestDB(t)
	app := createEventTestApplication(t, d)
	scheduled := time.Date(2026, 7, 3, 14, 0, 0, 0, time.UTC)
	if err := d.CreateEvent(&Event{ApplicationID: app.ID, EventType: "written_test", ScheduledAt: &scheduled, Duration: "120"}); err != nil {
		t.Fatalf("create event: %v", err)
	}

	if err := d.DeleteApplication(app.ID); err != nil {
		t.Fatalf("delete application: %v", err)
	}
	items, err := d.ListEvents(EventFilter{ApplicationID: app.ID})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(items) != 0 {
		t.Fatalf("expected cascade delete, got %+v", items)
	}
}
```

- [ ] **Step 2: Run DB tests and verify they fail**

Run:

```powershell
go test ./internal/db -run Event -count=1
```

Expected: fail because `CreateEvent`, `GetEvent`, `ListEvents`, `UpdateEvent`, `DeleteEvent`, and `EventFilter` are undefined.

- [ ] **Step 3: Implement DB event methods**

Create `internal/db/events.go`:

```go
package db

import (
	"database/sql"
	"fmt"
	"strings"
	"time"
)

type EventFilter struct {
	Month         string
	ApplicationID int64
	EventType     string
	Start         *time.Time
	End           *time.Time
}

type EventWithApplication struct {
	Event
	CompanyName  string `json:"company_name"`
	PositionName string `json:"position_name"`
}

func (db *Database) CreateEvent(event *Event) error {
	if event.CreatedAt.IsZero() {
		event.CreatedAt = time.Now()
	}
	res, err := db.conn.Exec(
		`INSERT INTO events (application_id, event_type, round, scheduled_at, duration, location, notes, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		event.ApplicationID, event.EventType, event.Round, event.ScheduledAt, event.Duration, event.Location, event.Notes, event.CreatedAt,
	)
	if err != nil {
		return err
	}
	event.ID, _ = res.LastInsertId()
	return nil
}

func (db *Database) GetEvent(id int64) (*Event, error) {
	var event Event
	err := db.conn.QueryRow(
		`SELECT id, application_id, event_type, round, scheduled_at, duration, location, notes, created_at
		 FROM events WHERE id = ?`,
		id,
	).Scan(&event.ID, &event.ApplicationID, &event.EventType, &event.Round, &event.ScheduledAt, &event.Duration, &event.Location, &event.Notes, &event.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &event, nil
}

func (db *Database) ListEvents(filter EventFilter) ([]EventWithApplication, error) {
	query := `SELECT e.id, e.application_id, e.event_type, e.round, e.scheduled_at, e.duration, e.location, e.notes, e.created_at,
	                 a.company_name, a.position_name
	          FROM events e
	          JOIN applications a ON a.id = e.application_id`
	var clauses []string
	var args []interface{}

	if filter.ApplicationID != 0 {
		clauses = append(clauses, "e.application_id = ?")
		args = append(args, filter.ApplicationID)
	}
	if filter.EventType != "" {
		clauses = append(clauses, "e.event_type = ?")
		args = append(args, filter.EventType)
	}
	if filter.Month != "" {
		start, err := time.Parse("2006-01", filter.Month)
		if err != nil {
			return nil, fmt.Errorf("parse month: %w", err)
		}
		end := start.AddDate(0, 1, 0)
		clauses = append(clauses, "e.scheduled_at >= ? AND e.scheduled_at < ?")
		args = append(args, start, end)
	}
	if filter.Start != nil {
		clauses = append(clauses, "e.scheduled_at >= ?")
		args = append(args, *filter.Start)
	}
	if filter.End != nil {
		clauses = append(clauses, "e.scheduled_at < ?")
		args = append(args, *filter.End)
	}
	if len(clauses) > 0 {
		query += " WHERE " + strings.Join(clauses, " AND ")
	}
	query += " ORDER BY e.scheduled_at ASC, e.id ASC"

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []EventWithApplication
	for rows.Next() {
		var item EventWithApplication
		if err := rows.Scan(
			&item.ID, &item.ApplicationID, &item.EventType, &item.Round, &item.ScheduledAt,
			&item.Duration, &item.Location, &item.Notes, &item.CreatedAt,
			&item.CompanyName, &item.PositionName,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

func (db *Database) ListEventsByApplication(applicationID int64) ([]EventWithApplication, error) {
	return db.ListEvents(EventFilter{ApplicationID: applicationID})
}

func (db *Database) UpdateEvent(event *Event) error {
	res, err := db.conn.Exec(
		`UPDATE events
		 SET application_id = ?, event_type = ?, round = ?, scheduled_at = ?, duration = ?, location = ?, notes = ?
		 WHERE id = ?`,
		event.ApplicationID, event.EventType, event.Round, event.ScheduledAt, event.Duration, event.Location, event.Notes, event.ID,
	)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if n == 0 {
		return sql.ErrNoRows
	}
	return nil
}

func (db *Database) DeleteEvent(id int64) error {
	res, err := db.conn.Exec(`DELETE FROM events WHERE id = ?`, id)
	if err != nil {
		return err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if n == 0 {
		return sql.ErrNoRows
	}
	return nil
}
```

- [ ] **Step 4: Enable SQLite foreign keys for cascade behavior**

Modify `internal/db/db.go` inside `Init` after `conn.SetMaxOpenConns(1)`:

```go
	if _, err := conn.Exec(`PRAGMA foreign_keys = ON`); err != nil {
		conn.Close()
		return nil, fmt.Errorf("enable foreign keys: %w", err)
	}
```

- [ ] **Step 5: Run DB tests and commit**

Run:

```powershell
go test ./internal/db -run Event -count=1
go test ./internal/db -count=1
```

Expected: both commands pass.

Commit:

```powershell
git add internal/db/db.go internal/db/events.go internal/db/events_test.go
git commit -m "feat: AI add schedule event storage"
```

---

### Task 2: Event API

**Files:**
- Create: `internal/api/events.go`
- Create: `internal/api/events_test.go`
- Modify: `internal/api/router.go`

- [ ] **Step 1: Write failing API tests**

Create `internal/api/events_test.go`:

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

func eventAPITestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/events.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func createEventAPIApplication(t *testing.T, d *db.Database) db.Application {
	t.Helper()
	app := db.Application{
		CompanyName:  "腾讯",
		PositionName: "客户端",
		Status:       "written_test",
		Source:       "test",
		AppliedAt:    time.Date(2026, 6, 30, 9, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(&app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	return app
}

func TestEventAPICRUD(t *testing.T) {
	d := eventAPITestDB(t)
	app := createEventAPIApplication(t, d)
	router := NewRouter(d, t.TempDir())

	body := map[string]interface{}{
		"application_id":   app.ID,
		"event_type":       "written_test",
		"scheduled_at":     "2026-07-05T10:00:00Z",
		"duration_minutes": 120,
		"location":         "线上笔试",
		"notes":            "提前调试摄像头",
	}
	payload, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/events", bytes.NewReader(payload))
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", rec.Code, rec.Body.String())
	}

	var created map[string]interface{}
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode create: %v", err)
	}
	id := int64(created["id"].(float64))
	if created["duration_minutes"].(float64) != 120 {
		t.Fatalf("unexpected duration: %v", created)
	}

	req = httptest.NewRequest(http.MethodGet, "/api/events?month=2026-07", nil)
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("list status %d: %s", rec.Code, rec.Body.String())
	}
	var listed []map[string]interface{}
	_ = json.Unmarshal(rec.Body.Bytes(), &listed)
	if len(listed) != 1 || listed[0]["company_name"] != "腾讯" {
		t.Fatalf("unexpected list: %+v", listed)
	}

	body["duration_minutes"] = 90
	body["event_type"] = "assessment"
	payload, _ = json.Marshal(body)
	req = httptest.NewRequest(http.MethodPut, "/api/events/"+strconv.FormatInt(id, 10), bytes.NewReader(payload))
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("update status %d: %s", rec.Code, rec.Body.String())
	}

	req = httptest.NewRequest(http.MethodDelete, "/api/events/"+strconv.FormatInt(id, 10), nil)
	rec = httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("delete status %d: %s", rec.Code, rec.Body.String())
	}
}

func TestEventAPIValidation(t *testing.T) {
	d := eventAPITestDB(t)
	app := createEventAPIApplication(t, d)
	router := NewRouter(d, t.TempDir())

	cases := []map[string]interface{}{
		{"application_id": app.ID, "event_type": "other", "scheduled_at": "2026-07-05T10:00:00Z", "duration_minutes": 60},
		{"application_id": app.ID, "event_type": "interview", "scheduled_at": "", "duration_minutes": 60},
		{"application_id": app.ID, "event_type": "interview", "scheduled_at": "2026-07-05T10:00:00Z", "duration_minutes": 0},
		{"application_id": 99999, "event_type": "interview", "scheduled_at": "2026-07-05T10:00:00Z", "duration_minutes": 60},
	}
	for _, body := range cases {
		payload, _ := json.Marshal(body)
		req := httptest.NewRequest(http.MethodPost, "/api/events", bytes.NewReader(payload))
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)
		if rec.Code < 400 {
			t.Fatalf("expected validation failure for %+v, got %d", body, rec.Code)
		}
	}
}
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```powershell
go test ./internal/api -run EventAPI -count=1
```

Expected: fail because `/api/events` routes do not exist.

- [ ] **Step 3: Implement API handlers**

Create `internal/api/events.go`:

```go
package api

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

type eventResponse struct {
	ID              int64  `json:"id"`
	ApplicationID   int64  `json:"application_id"`
	EventType       string `json:"event_type"`
	Round           int    `json:"round"`
	ScheduledAt     string `json:"scheduled_at"`
	DurationMinutes int    `json:"duration_minutes"`
	Location        string `json:"location"`
	Notes           string `json:"notes"`
	CompanyName     string `json:"company_name,omitempty"`
	PositionName    string `json:"position_name,omitempty"`
	CreatedAt       string `json:"created_at"`
}

type eventRequest struct {
	ApplicationID   int64  `json:"application_id"`
	EventType       string `json:"event_type"`
	Round           int    `json:"round"`
	ScheduledAt     string `json:"scheduled_at"`
	DurationMinutes int    `json:"duration_minutes"`
	Location        string `json:"location"`
	Notes           string `json:"notes"`
}

func registerEventRoutes(r chi.Router, database *db.Database) {
	r.Get("/events", listEvents(database))
	r.Post("/events", createEvent(database))
	r.Get("/events/{id}", getEvent(database))
	r.Put("/events/{id}", updateEvent(database))
	r.Delete("/events/{id}", deleteEvent(database))
}

func listEvents(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		applicationID, _ := strconv.ParseInt(r.URL.Query().Get("application_id"), 10, 64)
		items, err := database.ListEvents(db.EventFilter{
			Month:         r.URL.Query().Get("month"),
			ApplicationID: applicationID,
			EventType:     r.URL.Query().Get("type"),
		})
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid event filter")
			return
		}
		out := make([]eventResponse, 0, len(items))
		for _, item := range items {
			out = append(out, eventWithApplicationResponse(item))
		}
		respondJSON(w, http.StatusOK, out)
	}
}

func createEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		event, ok := decodeEventRequest(w, r, database, 0)
		if !ok {
			return
		}
		if err := database.CreateEvent(event); err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to create event")
			return
		}
		respondJSON(w, http.StatusCreated, eventResponseFromEvent(*event, "", ""))
	}
}

func getEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		event, err := database.GetEvent(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Event not found")
			return
		}
		respondJSON(w, http.StatusOK, eventResponseFromEvent(*event, "", ""))
	}
}

func updateEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		event, ok := decodeEventRequest(w, r, database, id)
		if !ok {
			return
		}
		if err := database.UpdateEvent(event); err != nil {
			if err == sql.ErrNoRows {
				respondError(w, http.StatusNotFound, "Event not found")
				return
			}
			respondError(w, http.StatusInternalServerError, "Failed to update event")
			return
		}
		respondJSON(w, http.StatusOK, eventResponseFromEvent(*event, "", ""))
	}
}

func deleteEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		if err := database.DeleteEvent(id); err != nil {
			if err == sql.ErrNoRows {
				respondError(w, http.StatusNotFound, "Event not found")
				return
			}
			respondError(w, http.StatusInternalServerError, "Failed to delete event")
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

func decodeEventRequest(w http.ResponseWriter, r *http.Request, database *db.Database, id int64) (*db.Event, bool) {
	var body eventRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respondError(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	if !validEventType(body.EventType) {
		respondError(w, http.StatusBadRequest, "Invalid event type")
		return nil, false
	}
	if body.DurationMinutes <= 0 {
		respondError(w, http.StatusBadRequest, "duration_minutes must be greater than 0")
		return nil, false
	}
	scheduled, err := time.Parse(time.RFC3339, body.ScheduledAt)
	if err != nil {
		respondError(w, http.StatusBadRequest, "scheduled_at must be RFC3339")
		return nil, false
	}
	if _, err := database.GetApplication(body.ApplicationID); err != nil {
		respondError(w, http.StatusNotFound, "Application not found")
		return nil, false
	}
	return &db.Event{
		ID:            id,
		ApplicationID: body.ApplicationID,
		EventType:     body.EventType,
		Round:         body.Round,
		ScheduledAt:   &scheduled,
		Duration:      strconv.Itoa(body.DurationMinutes),
		Location:      body.Location,
		Notes:         body.Notes,
	}, true
}

func eventIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}

func validEventType(t string) bool {
	return t == "written_test" || t == "interview" || t == "assessment"
}

func eventWithApplicationResponse(item db.EventWithApplication) eventResponse {
	return eventResponseFromEvent(item.Event, item.CompanyName, item.PositionName)
}

func eventResponseFromEvent(event db.Event, company string, position string) eventResponse {
	duration, _ := strconv.Atoi(event.Duration)
	scheduled := ""
	if event.ScheduledAt != nil {
		scheduled = event.ScheduledAt.UTC().Format(time.RFC3339)
	}
	return eventResponse{
		ID:              event.ID,
		ApplicationID:   event.ApplicationID,
		EventType:       event.EventType,
		Round:           event.Round,
		ScheduledAt:     scheduled,
		DurationMinutes: duration,
		Location:        event.Location,
		Notes:           event.Notes,
		CompanyName:     company,
		PositionName:    position,
		CreatedAt:       event.CreatedAt.UTC().Format(time.RFC3339),
	}
}
```

- [ ] **Step 4: Register event routes**

Modify `internal/api/router.go` inside the `/api` route block after the dashboard route:

```go
		// Schedule events
		registerEventRoutes(r, database)
```

- [ ] **Step 5: Run API tests and commit**

Run:

```powershell
go test ./internal/api -run EventAPI -count=1
go test ./internal/api -count=1
```

Expected: both commands pass.

Commit:

```powershell
git add internal/api/events.go internal/api/events_test.go internal/api/router.go
git commit -m "feat: AI add schedule event API"
```

---

### Task 3: Calendar Aggregation

**Files:**
- Modify: `internal/api/calendar.go`
- Create: `internal/api/calendar_test.go`

- [ ] **Step 1: Write failing calendar test**

Create `internal/api/calendar_test.go`:

```go
package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestCalendarIncludesEditableScheduleEvents(t *testing.T) {
	d := eventAPITestDB(t)
	app := createEventAPIApplication(t, d)
	scheduled := time.Date(2026, 7, 5, 10, 0, 0, 0, time.UTC)
	if err := d.CreateEvent(&db.Event{
		ApplicationID: app.ID,
		EventType:     "written_test",
		ScheduledAt:   &scheduled,
		Duration:      "120",
		Location:      "线上笔试",
	}); err != nil {
		t.Fatalf("create event: %v", err)
	}
	router := NewRouter(d, t.TempDir())

	req := httptest.NewRequest(http.MethodGet, "/api/calendar?month=2026-07", nil)
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}

	var entries []CalendarEntry
	if err := json.Unmarshal(rec.Body.Bytes(), &entries); err != nil {
		t.Fatalf("decode calendar: %v", err)
	}
	var found *CalendarEntry
	for i := range entries {
		if entries[i].Type == "written_test" {
			found = &entries[i]
			break
		}
	}
	if found == nil {
		t.Fatalf("expected written_test entry in %+v", entries)
	}
	if found.EventID == nil || !found.Editable || found.DurationMinutes != 120 || found.Location != "线上笔试" {
		t.Fatalf("unexpected schedule entry: %+v", found)
	}
}
```

- [ ] **Step 2: Run calendar test and verify it fails**

Run:

```powershell
go test ./internal/api -run CalendarIncludesEditableScheduleEvents -count=1
```

Expected: fail because `CalendarEntry` does not contain schedule-event fields and calendar aggregation does not include DB events.

- [ ] **Step 3: Extend `CalendarEntry` and aggregate events**

Modify `internal/api/calendar.go`:

```go
type CalendarEntry struct {
	Date            string `json:"date"`
	Type            string `json:"type"`
	Title           string `json:"title"`
	Subtitle        string `json:"subtitle,omitempty"`
	AppID           int64  `json:"app_id"`
	NoteID          *int64 `json:"note_id,omitempty"`
	EventID         *int64 `json:"event_id,omitempty"`
	EventType       string `json:"event_type,omitempty"`
	ScheduledAt     string `json:"scheduled_at,omitempty"`
	DurationMinutes int    `json:"duration_minutes,omitempty"`
	Location        string `json:"location,omitempty"`
	Editable        bool   `json:"editable,omitempty"`
}
```

Add this block before applied-date aggregation:

```go
		if events, eerr := database.ListEvents(db.EventFilter{Month: month.Format("2006-01")}); eerr == nil {
			for _, e := range events {
				if e.ScheduledAt == nil {
					continue
				}
				duration, _ := strconv.Atoi(e.Duration)
				title := e.CompanyName + " · " + eventTypeLabel(e.EventType)
				entries = append(entries, CalendarEntry{
					Date:            e.ScheduledAt.UTC().Format("2006-01-02"),
					Type:            e.EventType,
					Title:           title,
					Subtitle:        e.PositionName,
					AppID:           e.ApplicationID,
					EventID:         &e.ID,
					EventType:       e.EventType,
					ScheduledAt:     e.ScheduledAt.UTC().Format(time.RFC3339),
					DurationMinutes: duration,
					Location:        e.Location,
					Editable:        true,
				})
			}
		}
```

Add imports:

```go
	"strconv"
```

Add helper:

```go
func eventTypeLabel(t string) string {
	switch t {
	case "written_test":
		return "笔试"
	case "interview":
		return "面试"
	case "assessment":
		return "测评"
	default:
		return t
	}
}
```

- [ ] **Step 4: Run calendar/API tests and commit**

Run:

```powershell
go test ./internal/api -run Calendar -count=1
go test ./internal/api -count=1
```

Expected: both commands pass.

Commit:

```powershell
git add internal/api/calendar.go internal/api/calendar_test.go
git commit -m "feat: AI show schedule events on calendar"
```

---

### Task 4: AI Schedule Tools

**Files:**
- Modify: `internal/ai/tools.go`
- Modify: `internal/ai/tools_test.go`
- Modify: `internal/ai/summary.go`
- Modify: `internal/ai/summary_test.go`

- [ ] **Step 1: Write failing AI tool tests**

Append to `internal/ai/tools_test.go`:

```go
func TestScheduleEventTools(t *testing.T) {
	d := newToolDB(t)
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "test", AppliedAt: time.Now()})
	reg := NewRegistry(d)

	create, ok := reg.Get("create_event")
	if !ok || !create.Write {
		t.Fatal("create_event should be registered as a write tool")
	}
	if create.Describe(json.RawMessage(`{"application_id":1,"event_type":"interview","scheduled_at":"2026-07-03T14:00:00Z","duration_minutes":60}`)) == "" {
		t.Fatal("expected create_event confirmation text")
	}

	out, err := reg.Execute(context.Background(), "create_event", json.RawMessage(`{"application_id":1,"event_type":"interview","scheduled_at":"2026-07-03T14:00:00Z","duration_minutes":60,"location":"腾讯会议"}`))
	if err != nil {
		t.Fatalf("create_event execute: %v", err)
	}
	if !strings.Contains(out, `"event_type":"interview"`) {
		t.Fatalf("unexpected create output: %s", out)
	}

	out, err = reg.Execute(context.Background(), "list_events", json.RawMessage(`{"month":"2026-07"}`))
	if err != nil {
		t.Fatalf("list_events execute: %v", err)
	}
	if !strings.Contains(out, "腾讯会议") {
		t.Fatalf("unexpected list output: %s", out)
	}

	update, ok := reg.Get("update_event")
	if !ok || !update.Write {
		t.Fatal("update_event should be registered as a write tool")
	}
	if _, err := reg.Execute(context.Background(), "update_event", json.RawMessage(`{"id":1,"application_id":1,"event_type":"interview","scheduled_at":"2026-07-04T10:00:00Z","duration_minutes":90}`)); err != nil {
		t.Fatalf("update_event execute: %v", err)
	}

	del, ok := reg.Get("delete_event")
	if !ok || !del.Write {
		t.Fatal("delete_event should be registered as a write tool")
	}
	if _, err := reg.Execute(context.Background(), "delete_event", json.RawMessage(`{"id":1}`)); err != nil {
		t.Fatalf("delete_event execute: %v", err)
	}
}
```

Add imports if absent:

```go
	"context"
	"strings"
	"time"
```

- [ ] **Step 2: Run AI tests and verify they fail**

Run:

```powershell
go test ./internal/ai -run ScheduleEventTools -count=1
```

Expected: fail because event tools are not registered.

- [ ] **Step 3: Add event tools**

In `internal/ai/tools.go`, add helper functions near `jsonResult`:

```go
func parseToolTime(value string) (*time.Time, error) {
	if value == "" {
		return nil, fmt.Errorf("scheduled_at is required")
	}
	t, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return nil, err
	}
	return &t, nil
}

func durationString(minutes int) (string, error) {
	if minutes <= 0 {
		return "", fmt.Errorf("duration_minutes must be greater than 0")
	}
	return fmt.Sprintf("%d", minutes), nil
}
```

Register read tools after `list_notes`:

```go
	r.add(Tool{
		Name:        "list_events",
		Description: "列出笔试、面试、测评日程，可按 month(YYYY-MM)、application_id 或 event_type 过滤。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"month":{"type":"string"},"application_id":{"type":"integer"},"event_type":{"type":"string"}}}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				Month         string `json:"month"`
				ApplicationID int64  `json:"application_id"`
				EventType     string `json:"event_type"`
			}
			_ = json.Unmarshal(args, &p)
			items, err := database.ListEvents(db.EventFilter{Month: p.Month, ApplicationID: p.ApplicationID, EventType: p.EventType})
			if err != nil {
				return "", err
			}
			return jsonResult(items)
		},
	})
	r.add(Tool{
		Name:        "get_event",
		Description: "按 ID 获取单个日程事件。",
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ID int64 `json:"id"` }
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			event, err := database.GetEvent(p.ID)
			if err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
```

Register write tools before `return r`:

```go
	r.add(Tool{
		Name:        "create_event",
		Description: "创建绑定到投递记录的笔试、面试或测评日程。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"application_id":{"type":"integer"},"event_type":{"type":"string"},"round":{"type":"integer"},"scheduled_at":{"type":"string"},"duration_minutes":{"type":"integer"},"location":{"type":"string"},"notes":{"type":"string"}},"required":["application_id","event_type","scheduled_at","duration_minutes"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("为投递 #%d 创建 %s 的 %s 日程，时长 %d 分钟", p.ApplicationID, p.ScheduledAt, p.EventType, p.DurationMinutes)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				Round           int    `json:"round"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
				Location        string `json:"location"`
				Notes           string `json:"notes"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			scheduled, err := parseToolTime(p.ScheduledAt)
			if err != nil {
				return "", err
			}
			duration, err := durationString(p.DurationMinutes)
			if err != nil {
				return "", err
			}
			event := &db.Event{ApplicationID: p.ApplicationID, EventType: p.EventType, Round: p.Round, ScheduledAt: scheduled, Duration: duration, Location: p.Location, Notes: p.Notes}
			if err := database.CreateEvent(event); err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
	r.add(Tool{
		Name:        "update_event",
		Description: "修改笔试、面试或测评日程。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"},"application_id":{"type":"integer"},"event_type":{"type":"string"},"round":{"type":"integer"},"scheduled_at":{"type":"string"},"duration_minutes":{"type":"integer"},"location":{"type":"string"},"notes":{"type":"string"}},"required":["id","application_id","event_type","scheduled_at","duration_minutes"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct {
				ID              int64  `json:"id"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
			}
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("将日程 #%d 改为 %s，时长 %d 分钟", p.ID, p.ScheduledAt, p.DurationMinutes)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct {
				ID              int64  `json:"id"`
				ApplicationID   int64  `json:"application_id"`
				EventType       string `json:"event_type"`
				Round           int    `json:"round"`
				ScheduledAt     string `json:"scheduled_at"`
				DurationMinutes int    `json:"duration_minutes"`
				Location        string `json:"location"`
				Notes           string `json:"notes"`
			}
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			scheduled, err := parseToolTime(p.ScheduledAt)
			if err != nil {
				return "", err
			}
			duration, err := durationString(p.DurationMinutes)
			if err != nil {
				return "", err
			}
			event := &db.Event{ID: p.ID, ApplicationID: p.ApplicationID, EventType: p.EventType, Round: p.Round, ScheduledAt: scheduled, Duration: duration, Location: p.Location, Notes: p.Notes}
			if err := database.UpdateEvent(event); err != nil {
				return "", err
			}
			return jsonResult(event)
		},
	})
	r.add(Tool{
		Name:        "delete_event",
		Description: "删除一条笔试、面试或测评日程。",
		Write:       true,
		Schema:      json.RawMessage(`{"type":"object","properties":{"id":{"type":"integer"}},"required":["id"]}`),
		Describe: func(args json.RawMessage) string {
			var p struct{ ID int64 `json:"id"` }
			_ = json.Unmarshal(args, &p)
			return fmt.Sprintf("删除日程 #%d", p.ID)
		},
		Handler: func(ctx context.Context, args json.RawMessage) (string, error) {
			var p struct{ ID int64 `json:"id"` }
			if err := json.Unmarshal(args, &p); err != nil {
				return "", err
			}
			if err := database.DeleteEvent(p.ID); err != nil {
				return "", err
			}
			return jsonResult(map[string]interface{}{"deleted": true, "id": p.ID})
		},
	})
```

- [ ] **Step 4: Include schedule events in summary fallback**

Modify `internal/ai/summary.go` inside `BuildDataSummary` after notes are listed:

```go
	if events, err := database.ListEvents(db.EventFilter{}); err == nil && len(events) > 0 {
		b.WriteString("\n日程事件:\n")
		for _, e := range events {
			when := ""
			if e.ScheduledAt != nil {
				when = e.ScheduledAt.Format("2006-01-02 15:04")
			}
			b.WriteString(fmt.Sprintf("- #%d %s %s %s %s 时长%s分钟\n", e.ID, e.CompanyName, e.PositionName, e.EventType, when, e.Duration))
		}
	}
```

Update `internal/ai/summary_test.go` to create one event and assert the summary contains `interview` and `2026-07-03`.

- [ ] **Step 5: Run AI tests and commit**

Run:

```powershell
go test ./internal/ai -run "ScheduleEventTools|Summary" -count=1
go test ./internal/ai -count=1
```

Expected: both commands pass.

Commit:

```powershell
git add internal/ai/tools.go internal/ai/tools_test.go internal/ai/summary.go internal/ai/summary_test.go
git commit -m "feat: AI manage schedule events from chat"
```

---

### Task 5: Frontend Event Types, Service, And Shared Form

**Files:**
- Create: `web/src/types/event.ts`
- Create: `web/src/services/events.ts`
- Create: `web/src/components/ScheduleEventForm.tsx`

- [ ] **Step 1: Add frontend event types**

Create `web/src/types/event.ts`:

```ts
export type ScheduleEventType = 'written_test' | 'interview' | 'assessment';

export const EVENT_TYPE_LABELS: Record<ScheduleEventType, string> = {
  written_test: '笔试',
  interview: '面试',
  assessment: '测评',
};

export interface ScheduleEvent {
  id: number;
  application_id: number;
  event_type: ScheduleEventType;
  round: number;
  scheduled_at: string;
  duration_minutes: number;
  location: string;
  notes: string;
  company_name?: string;
  position_name?: string;
  created_at: string;
}

export interface ScheduleEventInput {
  application_id: number;
  event_type: ScheduleEventType;
  round?: number;
  scheduled_at: string;
  duration_minutes: number;
  location?: string;
  notes?: string;
}
```

- [ ] **Step 2: Add event service**

Create `web/src/services/events.ts`:

```ts
import axios from 'axios';
import type { ScheduleEvent, ScheduleEventInput, ScheduleEventType } from '@/types/event';

const http = axios.create({
  baseURL: '/api',
  timeout: 10000,
});

interface ListEventsParams {
  month?: string;
  application_id?: number;
  type?: ScheduleEventType;
}

export async function listEvents(params?: ListEventsParams): Promise<ScheduleEvent[]> {
  const { data } = await http.get<ScheduleEvent[]>('/events', { params });
  return data;
}

export async function createEvent(input: ScheduleEventInput): Promise<ScheduleEvent> {
  const { data } = await http.post<ScheduleEvent>('/events', input);
  return data;
}

export async function updateEvent(id: number, input: ScheduleEventInput): Promise<ScheduleEvent> {
  const { data } = await http.put<ScheduleEvent>(`/events/${id}`, input);
  return data;
}

export async function deleteEvent(id: number): Promise<void> {
  await http.delete(`/events/${id}`);
}
```

- [ ] **Step 3: Add shared schedule form**

Create `web/src/components/ScheduleEventForm.tsx`:

```tsx
import { useEffect } from 'react';
import { Button, DatePicker, Drawer, Form, Input, InputNumber, Select, Space, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import dayjs from 'dayjs';
import type { Application } from '@/types/application';
import type { ScheduleEvent, ScheduleEventInput, ScheduleEventType } from '@/types/event';
import { EVENT_TYPE_LABELS } from '@/types/event';
import { createEvent, updateEvent } from '@/services/events';

interface Props {
  open: boolean;
  applications: Application[];
  initialApplication?: Application | null;
  event?: ScheduleEvent | null;
  onClose: () => void;
}

interface FormValues {
  application_id: number;
  event_type: ScheduleEventType;
  round?: number;
  scheduled_at: dayjs.Dayjs;
  duration_minutes: number;
  location?: string;
  notes?: string;
}

export default function ScheduleEventForm({ open, applications, initialApplication, event, onClose }: Props) {
  const [form] = Form.useForm<FormValues>();
  const queryClient = useQueryClient();
  const isEdit = !!event;

  useEffect(() => {
    if (!open) return;
    if (event) {
      form.setFieldsValue({
        application_id: event.application_id,
        event_type: event.event_type,
        round: event.round || undefined,
        scheduled_at: dayjs(event.scheduled_at),
        duration_minutes: event.duration_minutes,
        location: event.location,
        notes: event.notes,
      });
      return;
    }
    form.setFieldsValue({
      application_id: initialApplication?.id,
      event_type: 'interview',
      duration_minutes: 60,
      scheduled_at: dayjs().add(1, 'day').minute(0).second(0),
    });
  }, [event, form, initialApplication, open]);

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const input: ScheduleEventInput = {
        application_id: values.application_id,
        event_type: values.event_type,
        round: values.round ?? 0,
        scheduled_at: values.scheduled_at.toISOString(),
        duration_minutes: values.duration_minutes,
        location: values.location ?? '',
        notes: values.notes ?? '',
      };
      return isEdit && event ? updateEvent(event.id, input) : createEvent(input);
    },
    onSuccess: () => {
      message.success(isEdit ? '日程已更新' : '日程已创建');
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
      queryClient.invalidateQueries({ queryKey: ['events'] });
      onClose();
    },
    onError: () => {
      message.error(isEdit ? '更新日程失败' : '创建日程失败');
    },
  });

  return (
    <Drawer
      title={isEdit ? '编辑日程' : '新建日程'}
      open={open}
      onClose={onClose}
      width={420}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={mutation.isPending} onClick={() => form.submit()}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
        <Form.Item name="application_id" label="投递记录" rules={[{ required: true, message: '请选择投递记录' }]}>
          <Select
            disabled={!!initialApplication || isEdit}
            showSearch
            optionFilterProp="label"
            options={applications.map((app) => ({
              value: app.id,
              label: `${app.company_name} · ${app.position_name}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="event_type" label="类型" rules={[{ required: true }]}>
          <Select
            options={Object.entries(EVENT_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
          />
        </Form.Item>
        <Form.Item name="scheduled_at" label="开始时间" rules={[{ required: true, message: '请选择开始时间' }]}>
          <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="duration_minutes" label="时长（分钟）" rules={[{ required: true, message: '请输入时长' }]}>
          <InputNumber min={1} max={600} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="round" label="轮次">
          <InputNumber min={0} max={20} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="location" label="地点 / 链接">
          <Input />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={4} />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
```

- [ ] **Step 4: Run frontend build and commit**

Run:

```powershell
npm.cmd run build
```

Expected: TypeScript and Vite build pass.

Commit:

```powershell
git add web/src/types/event.ts web/src/services/events.ts web/src/components/ScheduleEventForm.tsx
git commit -m "feat: AI add schedule event form"
```

---

### Task 6: Calendar UI Integration

**Files:**
- Modify: `web/src/types/calendar.ts`
- Modify: `web/src/components/CalendarView.tsx`
- Modify: `web/src/components/CalendarView.module.css`

- [ ] **Step 1: Extend calendar types**

Modify `web/src/types/calendar.ts`:

```ts
import type { ScheduleEventType } from '@/types/event';

export type CalendarEntryType = 'interview' | 'applied' | 'written_test' | 'assessment';

export interface CalendarEntry {
  date: string;
  type: CalendarEntryType;
  title: string;
  subtitle?: string;
  app_id: number;
  note_id?: number;
  event_id?: number;
  event_type?: ScheduleEventType;
  scheduled_at?: string;
  duration_minutes?: number;
  location?: string;
  editable?: boolean;
}
```

- [ ] **Step 2: Add calendar form state and callbacks**

Modify `web/src/components/CalendarView.tsx` imports:

```tsx
import { DeleteOutlined, EditOutlined, LeftOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons';
import { Button, Spin, Empty, Tag, Drawer, Tooltip, Popconfirm, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import { EVENT_TYPE_LABELS } from '@/types/event';
import type { ScheduleEvent } from '@/types/event';
import { deleteEvent } from '@/services/events';
```

Add state inside the component:

```tsx
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editingEvent, setEditingEvent] = useState<ScheduleEvent | null>(null);
```

Add delete mutation:

```tsx
  const deleteMutation = useMutation({
    mutationFn: deleteEvent,
    onSuccess: () => {
      message.success('日程已删除');
      queryClient.invalidateQueries({ queryKey: ['calendar'] });
      setSelectedDate(null);
    },
    onError: () => message.error('删除日程失败'),
  });
```

Add converter:

```tsx
  const toScheduleEvent = (e: CalendarEntry): ScheduleEvent | null => {
    if (!e.event_id || !e.event_type || !e.scheduled_at) return null;
    return {
      id: e.event_id,
      application_id: e.app_id,
      event_type: e.event_type,
      round: 0,
      scheduled_at: e.scheduled_at,
      duration_minutes: e.duration_minutes ?? 60,
      location: e.location ?? '',
      notes: '',
      company_name: e.title,
      position_name: e.subtitle,
      created_at: '',
    };
  };
```

- [ ] **Step 3: Add toolbar create button**

In the toolbar JSX, add:

```tsx
        <Button
          type="primary"
          size="small"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingEvent(null);
            setFormOpen(true);
          }}
          style={{ marginLeft: 'auto' }}
        >
          新建日程
        </Button>
```

- [ ] **Step 4: Render schedule chips in date cells**

Inside each active calendar cell, replace dot-only display with:

```tsx
                  {dayEntries.length > 0 && (
                    <div className={styles.entries}>
                      {dayEntries.slice(0, 3).map((e) => (
                        <div key={`${e.type}-${e.event_id ?? e.note_id ?? e.title}`} className={styles.entryChip}>
                          {e.scheduled_at ? dayjs(e.scheduled_at).format('HH:mm') + ' ' : ''}
                          {e.event_type ? EVENT_TYPE_LABELS[e.event_type] : e.type === 'applied' ? '投递' : '复盘'}
                        </div>
                      ))}
                      {dayEntries.length > 3 && <span className={styles.count}>+{dayEntries.length - 3}</span>}
                    </div>
                  )}
```

- [ ] **Step 5: Add edit/delete actions in date drawer**

In the drawer entry rendering, add actions when `e.editable` is true:

```tsx
                  {e.editable && (
                    <Space>
                      <Button
                        size="small"
                        shape="circle"
                        icon={<EditOutlined />}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          const event = toScheduleEvent(e);
                          if (event) {
                            setEditingEvent(event);
                            setFormOpen(true);
                          }
                        }}
                      />
                      <Popconfirm
                        title="删除这条日程？"
                        okText="删除"
                        cancelText="取消"
                        onConfirm={(ev) => {
                          ev?.stopPropagation();
                          if (e.event_id) deleteMutation.mutate(e.event_id);
                        }}
                      >
                        <Button
                          size="small"
                          shape="circle"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={(ev) => ev.stopPropagation()}
                        />
                      </Popconfirm>
                    </Space>
                  )}
```

Render the shared form at the end of the component:

```tsx
      <ScheduleEventForm
        open={formOpen}
        applications={applications}
        event={editingEvent}
        onClose={() => {
          setFormOpen(false);
          setEditingEvent(null);
        }}
      />
```

- [ ] **Step 6: Add calendar chip styles**

Append to `web/src/components/CalendarView.module.css`:

```css
.entries {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-top: 6px;
  min-height: 44px;
}

.entryChip {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 4px;
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
  font-size: 11px;
  line-height: 18px;
  padding: 0 5px;
}
```

- [ ] **Step 7: Build and commit**

Run:

```powershell
npm.cmd run build
```

Expected: build passes.

Commit:

```powershell
git add web/src/types/calendar.ts web/src/components/CalendarView.tsx web/src/components/CalendarView.module.css
git commit -m "feat: AI manage schedules on calendar"
```

---

### Task 7: Application Detail Schedule Section

**Files:**
- Modify: `web/src/components/ApplicationDetail.tsx`

- [ ] **Step 1: Add event query to application detail**

In `web/src/components/ApplicationDetail.tsx`, add imports:

```tsx
import { CalendarOutlined, PlusOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import ScheduleEventForm from '@/components/ScheduleEventForm';
import { listEvents } from '@/services/events';
import { EVENT_TYPE_LABELS } from '@/types/event';
```

Inside the component, add:

```tsx
  const [eventFormOpen, setEventFormOpen] = useState(false);
  const { data: events = [] } = useQuery({
    queryKey: ['events', application?.id],
    queryFn: () => listEvents({ application_id: application!.id }),
    enabled: !!application?.id && open,
  });
```

- [ ] **Step 2: Render schedule section**

Add this section near notes/status details:

```tsx
        <Divider />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            <CalendarOutlined /> 日程
          </Typography.Title>
          <Button size="small" icon={<PlusOutlined />} onClick={() => setEventFormOpen(true)}>
            安排日程
          </Button>
        </div>
        {events.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无笔试、面试或测评日程" />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }}>
            {events.map((event) => (
              <div key={event.id} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <strong>{EVENT_TYPE_LABELS[event.event_type]}</strong>
                  <span>{dayjs(event.scheduled_at).format('YYYY-MM-DD HH:mm')}</span>
                </div>
                <div style={{ color: '#64748b', fontSize: 13 }}>
                  时长 {event.duration_minutes} 分钟{event.location ? ` · ${event.location}` : ''}
                </div>
              </div>
            ))}
          </Space>
        )}
```

Ensure `dayjs`, `Divider`, `Empty`, `Space`, and `Typography` are imported if they are not already present.

- [ ] **Step 3: Mount prefilled form**

Near the existing drawer/modal children, add:

```tsx
      {application && (
        <ScheduleEventForm
          open={eventFormOpen}
          applications={[application]}
          initialApplication={application}
          onClose={() => setEventFormOpen(false)}
        />
      )}
```

- [ ] **Step 4: Build and commit**

Run:

```powershell
npm.cmd run build
```

Expected: build passes.

Commit:

```powershell
git add web/src/components/ApplicationDetail.tsx
git commit -m "feat: AI add application schedule section"
```

---

### Task 8: Final Verification And Documentation Check

**Files:**
- Modify only files needed to fix failures found by verification.

- [ ] **Step 1: Run full backend tests**

Run:

```powershell
go test ./...
```

Expected: all packages pass.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm.cmd run build
```

Expected: TypeScript and Vite build pass. The existing Vite chunk-size warning can remain.

- [ ] **Step 3: Check git status**

Run:

```powershell
git status --short
```

Expected: no unstaged files except ignored build/dependency artifacts such as `web/dist/`, `web/node_modules/`, and `.superpowers/`.

- [ ] **Step 4: Commit verification fixes if any files changed**

If verification required code changes, commit them:

```powershell
git add <changed-files>
git commit -m "fix: AI stabilize schedule management"
```

If no files changed, do not create an empty commit.
