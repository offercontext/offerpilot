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

func TestUpdateApplicationMaterialKitMissingReturnsNoRows(t *testing.T) {
	d, err := Init(t.TempDir() + "/kits_update_missing.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	kit := &ApplicationMaterialKit{ID: 999, ApplicationID: 999, Status: "draft", ContentJSON: `{}`}
	if err := d.UpdateApplicationMaterialKit(kit); err != sql.ErrNoRows {
		t.Fatalf("expected sql.ErrNoRows, got %v", err)
	}
	if !kit.UpdatedAt.IsZero() {
		t.Fatalf("expected UpdatedAt to remain zero on failed update, got %v", kit.UpdatedAt)
	}
}
