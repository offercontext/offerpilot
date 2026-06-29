package db

import (
	"database/sql"
	"errors"
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
	scheduledAt := time.Date(2026, 6, 30, 14, 30, 0, 0, time.UTC)

	event := Event{
		ApplicationID: app.ID,
		EventType:     "interview",
		Round:         1,
		ScheduledAt:   &scheduledAt,
		Duration:      "60m",
		Location:      "Zoom",
		Notes:         "tech interview",
	}
	if err := d.CreateEvent(&event); err != nil {
		t.Fatalf("create event: %v", err)
	}
	if event.ID == 0 {
		t.Fatal("expected non-zero event id")
	}

	got, err := d.GetEvent(event.ID)
	if err != nil {
		t.Fatalf("get event: %v", err)
	}
	if got.ApplicationID != app.ID || got.EventType != "interview" || got.Round != 1 || got.Duration != "60m" || got.Location != "Zoom" || got.Notes != "tech interview" {
		t.Fatalf("unexpected event: %+v", got)
	}
	if got.ScheduledAt == nil || !got.ScheduledAt.Equal(scheduledAt) {
		t.Fatalf("unexpected scheduled_at: %v", got.ScheduledAt)
	}

	events, err := d.ListEventsByApplication(app.ID)
	if err != nil {
		t.Fatalf("list events by application: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("want 1 event, got %d", len(events))
	}
	if events[0].CompanyName != app.CompanyName || events[0].PositionName != app.PositionName {
		t.Fatalf("missing application details: %+v", events[0])
	}

	updatedAt := time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC)
	event.EventType = "written_test"
	event.Round = 2
	event.ScheduledAt = &updatedAt
	event.Duration = "90m"
	event.Location = "Online"
	event.Notes = "coding test"
	if err := d.UpdateEvent(&event); err != nil {
		t.Fatalf("update event: %v", err)
	}

	updated, err := d.GetEvent(event.ID)
	if err != nil {
		t.Fatalf("get updated event: %v", err)
	}
	if updated.EventType != "written_test" || updated.Round != 2 || updated.Duration != "90m" || updated.Location != "Online" || updated.Notes != "coding test" {
		t.Fatalf("unexpected updated event: %+v", updated)
	}
	if updated.ScheduledAt == nil || !updated.ScheduledAt.Equal(updatedAt) {
		t.Fatalf("unexpected updated scheduled_at: %v", updated.ScheduledAt)
	}

	if err := d.DeleteEvent(event.ID); err != nil {
		t.Fatalf("delete event: %v", err)
	}
	if _, err := d.GetEvent(event.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected sql.ErrNoRows after delete, got %v", err)
	}
	if err := d.UpdateEvent(&event); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected sql.ErrNoRows updating missing event, got %v", err)
	}
	if err := d.DeleteEvent(event.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected sql.ErrNoRows deleting missing event, got %v", err)
	}
}

func TestListEventsByMonthAndType(t *testing.T) {
	d := newTestDB(t)
	app := createEventTestApplication(t, d)

	juneInterview := time.Date(2026, 6, 1, 9, 0, 0, 0, time.UTC)
	juneAssessment := time.Date(2026, 6, 15, 9, 0, 0, 0, time.UTC)
	julyInterview := time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC)
	for _, event := range []Event{
		{ApplicationID: app.ID, EventType: "interview", Round: 2, ScheduledAt: &juneInterview},
		{ApplicationID: app.ID, EventType: "assessment", Round: 1, ScheduledAt: &juneAssessment},
		{ApplicationID: app.ID, EventType: "interview", Round: 3, ScheduledAt: &julyInterview},
	} {
		e := event
		if err := d.CreateEvent(&e); err != nil {
			t.Fatalf("create event: %v", err)
		}
	}

	events, err := d.ListEvents(EventFilter{Month: "2026-06", EventType: "interview"})
	if err != nil {
		t.Fatalf("list events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("want 1 event, got %d: %+v", len(events), events)
	}
	if events[0].EventType != "interview" || events[0].Round != 2 || events[0].ScheduledAt == nil || !events[0].ScheduledAt.Equal(juneInterview) {
		t.Fatalf("unexpected filtered event: %+v", events[0])
	}
}

func TestApplicationDeleteCascadesEvents(t *testing.T) {
	d := newTestDB(t)
	app := createEventTestApplication(t, d)
	scheduledAt := time.Date(2026, 6, 30, 14, 30, 0, 0, time.UTC)
	event := Event{
		ApplicationID: app.ID,
		EventType:     "interview",
		ScheduledAt:   &scheduledAt,
	}
	if err := d.CreateEvent(&event); err != nil {
		t.Fatalf("create event: %v", err)
	}

	if err := d.DeleteApplication(app.ID); err != nil {
		t.Fatalf("delete application: %v", err)
	}

	events, err := d.ListEventsByApplication(app.ID)
	if err != nil {
		t.Fatalf("list events by application: %v", err)
	}
	if len(events) != 0 {
		t.Fatalf("expected cascade delete of events, got %d", len(events))
	}
	if _, err := d.GetEvent(event.ID); !errors.Is(err, sql.ErrNoRows) {
		t.Fatalf("expected sql.ErrNoRows after cascade delete, got %v", err)
	}
}
