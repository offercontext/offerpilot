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
	app := db.Application{CompanyName: "ByteDance", PositionName: "Backend Engineer", Status: "interview", Source: "test", AppliedAt: time.Date(2026, 6, 30, 10, 0, 0, 0, time.UTC)}
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
	createBody := map[string]interface{}{"company": "Tencent", "position": "Frontend Engineer", "round": "Round 1", "date": "2026-07-01", "questions": "React performance", "self_reflection": "Need clearer tradeoffs", "difficulty_points": "Virtual list", "mood": "normal"}
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

	updateBody := map[string]interface{}{"company": "Tencent", "position": "Frontend Engineer", "round": "Round 2", "date": "2026-07-02", "questions": "Project deep dive", "self_reflection": "Answered with examples", "difficulty_points": "System design", "mood": "good"}
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
	createRec := noteAPIRequest(t, router, http.MethodPost, "/api/notes", map[string]interface{}{"application_id": app.ID, "round": "Round 1", "questions": "Go scheduler", "self_reflection": "Solid answer", "difficulty_points": "Runtime details"})
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
