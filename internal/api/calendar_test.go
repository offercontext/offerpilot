package api

import (
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestCalendarIncludesEditableScheduleEvents(t *testing.T) {
	d, app, router := eventTestDB(t)
	scheduledAt := time.Date(2026, 7, 5, 10, 0, 0, 0, time.UTC)
	location := "\u7ebf\u4e0a\u7b14\u8bd5"
	event := db.Event{
		ApplicationID: app.ID,
		EventType:     "written_test",
		ScheduledAt:   &scheduledAt,
		Duration:      "120",
		Location:      location,
	}
	if err := d.CreateEvent(&event); err != nil {
		t.Fatalf("create event: %v", err)
	}

	rec := eventAPIRequest(t, router, http.MethodGet, "/api/calendar?month=2026-07", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("calendar status %d: %s", rec.Code, rec.Body.String())
	}

	var entries []CalendarEntry
	if err := json.Unmarshal(rec.Body.Bytes(), &entries); err != nil {
		t.Fatalf("decode calendar entries: %v", err)
	}

	for _, entry := range entries {
		if entry.Type != "written_test" {
			continue
		}
		if entry.EventID == nil {
			t.Fatalf("expected event_id to be set: %+v", entry)
		}
		if !entry.Editable {
			t.Fatalf("expected schedule event to be editable: %+v", entry)
		}
		if entry.DurationMinutes != 120 {
			t.Fatalf("expected duration_minutes 120, got %d: %+v", entry.DurationMinutes, entry)
		}
		if entry.Location != location {
			t.Fatalf("expected location %s, got %q: %+v", location, entry.Location, entry)
		}
		return
	}

	t.Fatalf("expected written_test calendar entry, got %+v", entries)
}
