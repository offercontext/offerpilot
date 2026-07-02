package db

import (
	"database/sql"
	"errors"
	"testing"
)

func TestUpdateResumeText(t *testing.T) {
	d, err := Init(t.TempDir() + "/resume.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	r := &Resume{ParsedData: "", ParseStatus: "parse-failed"}
	if err := d.CreateResume(r); err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := d.UpdateResumeText(r.ID, "corrected text", "text-ready"); err != nil {
		t.Fatalf("update: %v", err)
	}
	got, err := d.GetResume(r.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.ParsedData != "corrected text" {
		t.Fatalf("parsed_data = %q, want %q", got.ParsedData, "corrected text")
	}
	if got.ParseStatus != "text-ready" {
		t.Fatalf("parse_status = %q, want %q", got.ParseStatus, "text-ready")
	}

	// Missing ID returns sql.ErrNoRows.
	err = d.UpdateResumeText(999999, "x", "text-ready")
	if !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("missing-id error = %v, want sql.ErrNoRows", err)
	}
}

func TestUpdateResumeFile(t *testing.T) {
	d, err := Init(t.TempDir() + "/resume2.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	t.Cleanup(func() { d.Close() })

	r := &Resume{ParsedData: "orig", ParseStatus: "text-ready"}
	if err := d.CreateResume(r); err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := d.UpdateResumeFile(r.ID, "resumes/1_resume.pdf"); err != nil {
		t.Fatalf("update file: %v", err)
	}
	got, err := d.GetResume(r.ID)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if got.FilePath != "resumes/1_resume.pdf" {
		t.Fatalf("file_path = %q, want %q", got.FilePath, "resumes/1_resume.pdf")
	}
}