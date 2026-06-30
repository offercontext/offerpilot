package ai

import (
	"strings"
	"testing"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestBuildDataSummaryIncludesApplications(t *testing.T) {
	d, err := db.Init(t.TempDir() + "/s.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	defer d.Close()
	_ = d.CreateApplication(&db.Application{CompanyName: "字节", PositionName: "后端", Status: "interview", Source: "cli"})

	summary := BuildDataSummary(d)
	if !strings.Contains(summary, "字节") || !strings.Contains(summary, "interview") {
		t.Fatalf("summary missing application info: %s", summary)
	}
}

func TestBuildDataSummaryIncludesScheduleEvents(t *testing.T) {
	d, err := db.Init(t.TempDir() + "/s.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	defer d.Close()
	app := &db.Application{
		CompanyName: "Tencent", PositionName: "Backend", Status: "interview", Source: "test",
		AppliedAt: time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	scheduledAt := time.Date(2026, 7, 3, 14, 0, 0, 0, time.UTC)
	if err := d.CreateEvent(&db.Event{
		ApplicationID: app.ID,
		EventType:     "interview",
		ScheduledAt:   &scheduledAt,
		Duration:      "60m",
		Location:      "腾讯会议",
	}); err != nil {
		t.Fatalf("create event: %v", err)
	}

	summary := BuildDataSummary(d)
	if !strings.Contains(summary, "interview") || !strings.Contains(summary, "2026-07-03") {
		t.Fatalf("summary missing schedule event info: %s", summary)
	}
}
