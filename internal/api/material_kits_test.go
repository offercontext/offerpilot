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
