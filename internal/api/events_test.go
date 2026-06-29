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

func eventTestDB(t *testing.T) (*db.Database, db.Application, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/events.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	app := db.Application{
		CompanyName:  "ByteDance",
		PositionName: "Backend Engineer",
		Status:       "interview",
		Source:       "test",
		AppliedAt:    time.Date(2026, 6, 29, 10, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(&app); err != nil {
		t.Fatalf("create application: %v", err)
	}

	return d, app, NewRouter(d, t.TempDir())
}

func eventAPIRequest(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal request body: %v", err)
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

func TestEventAPICRUD(t *testing.T) {
	_, app, router := eventTestDB(t)
	scheduledAt := time.Date(2026, 6, 30, 14, 30, 0, 0, time.UTC).Format(time.RFC3339)

	createBody := map[string]interface{}{
		"application_id":   app.ID,
		"event_type":       "interview",
		"round":            1,
		"scheduled_at":     scheduledAt,
		"duration_minutes": 60,
		"location":         "Zoom",
		"notes":            "technical interview",
	}
	createRec := eventAPIRequest(t, router, http.MethodPost, "/api/events", createBody)
	if createRec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", createRec.Code, createRec.Body.String())
	}
	var created map[string]interface{}
	if err := json.Unmarshal(createRec.Body.Bytes(), &created); err != nil {
		t.Fatalf("decode created event: %v", err)
	}
	if created["duration_minutes"] != float64(60) {
		t.Fatalf("expected duration_minutes 60, got %v", created["duration_minutes"])
	}
	eventID := int64(created["id"].(float64))

	listPath := "/api/events?month=2026-06&application_id=" + strconv.FormatInt(app.ID, 10) + "&type=interview"
	listRec := eventAPIRequest(t, router, http.MethodGet, listPath, nil)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list status %d: %s", listRec.Code, listRec.Body.String())
	}
	var listed []map[string]interface{}
	if err := json.Unmarshal(listRec.Body.Bytes(), &listed); err != nil {
		t.Fatalf("decode listed events: %v", err)
	}
	if len(listed) != 1 {
		t.Fatalf("want 1 listed event, got %d: %+v", len(listed), listed)
	}
	if listed[0]["company_name"] != app.CompanyName || listed[0]["position_name"] != app.PositionName {
		t.Fatalf("missing application names in list response: %+v", listed[0])
	}

	getRec := eventAPIRequest(t, router, http.MethodGet, "/api/events/"+strconv.FormatInt(eventID, 10), nil)
	if getRec.Code != http.StatusOK {
		t.Fatalf("get status %d: %s", getRec.Code, getRec.Body.String())
	}

	updateBody := map[string]interface{}{
		"application_id":   app.ID,
		"event_type":       "written_test",
		"round":            2,
		"scheduled_at":     time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC).Format(time.RFC3339),
		"duration_minutes": 90,
		"location":         "Online",
		"notes":            "coding test",
	}
	updateRec := eventAPIRequest(t, router, http.MethodPut, "/api/events/"+strconv.FormatInt(eventID, 10), updateBody)
	if updateRec.Code != http.StatusOK {
		t.Fatalf("update status %d: %s", updateRec.Code, updateRec.Body.String())
	}
	var updated map[string]interface{}
	if err := json.Unmarshal(updateRec.Body.Bytes(), &updated); err != nil {
		t.Fatalf("decode updated event: %v", err)
	}
	if updated["event_type"] != "written_test" || updated["duration_minutes"] != float64(90) {
		t.Fatalf("unexpected updated event: %+v", updated)
	}

	deleteRec := eventAPIRequest(t, router, http.MethodDelete, "/api/events/"+strconv.FormatInt(eventID, 10), nil)
	if deleteRec.Code != http.StatusOK {
		t.Fatalf("delete status %d: %s", deleteRec.Code, deleteRec.Body.String())
	}
	missingRec := eventAPIRequest(t, router, http.MethodGet, "/api/events/"+strconv.FormatInt(eventID, 10), nil)
	if missingRec.Code != http.StatusNotFound {
		t.Fatalf("expected deleted event to return 404, got %d: %s", missingRec.Code, missingRec.Body.String())
	}
}

func TestEventAPIValidation(t *testing.T) {
	_, app, router := eventTestDB(t)
	validTime := time.Date(2026, 6, 30, 14, 30, 0, 0, time.UTC).Format(time.RFC3339)

	cases := []struct {
		name string
		body map[string]interface{}
	}{
		{
			name: "invalid type",
			body: map[string]interface{}{"application_id": app.ID, "event_type": "other", "scheduled_at": validTime, "duration_minutes": 60},
		},
		{
			name: "missing scheduled_at",
			body: map[string]interface{}{"application_id": app.ID, "event_type": "interview", "duration_minutes": 60},
		},
		{
			name: "duration zero",
			body: map[string]interface{}{"application_id": app.ID, "event_type": "interview", "scheduled_at": validTime, "duration_minutes": 0},
		},
		{
			name: "missing application",
			body: map[string]interface{}{"application_id": app.ID + 999, "event_type": "interview", "scheduled_at": validTime, "duration_minutes": 60},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := eventAPIRequest(t, router, http.MethodPost, "/api/events", tc.body)
			if rec.Code < http.StatusBadRequest {
				t.Fatalf("expected >=400, got %d: %s", rec.Code, rec.Body.String())
			}
		})
	}
}
