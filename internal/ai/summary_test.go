package ai

import (
	"strings"
	"testing"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

func summaryTestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/summary.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestSummaryFallbackIncludesKnowledgeSearchContext(t *testing.T) {
	d := summaryTestDB(t)
	base := &db.KnowledgeBase{Name: "Java interview prep"}
	if err := d.CreateKnowledgeBase(base); err != nil {
		t.Fatalf("create base: %v", err)
	}
	doc := &db.KnowledgeDocument{KnowledgeBaseID: base.ID, Title: "Synchronized", Content: "synchronized uses monitor locks", SourceType: db.KnowledgeSourceManual}
	if err := d.CreateKnowledgeDocument(doc); err != nil {
		t.Fatalf("create doc: %v", err)
	}

	system, user := BuildSummaryFallbackPrompt(d, "Explain synchronized")
	if !strings.Contains(system, "OfferPilot") {
		t.Fatalf("expected existing system prompt context, got %s", system)
	}
	if !strings.Contains(user, "Knowledge snippets") || !strings.Contains(user, "Synchronized") || !strings.Contains(user, "monitor locks") {
		t.Fatalf("expected knowledge context in fallback prompt, got %s", user)
	}
}

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

func TestBuildDataSummaryLimitsScheduleEventsAndFormatsDuration(t *testing.T) {
	d, err := db.Init(t.TempDir() + "/s.db")
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	defer d.Close()
	app := &db.Application{
		CompanyName: "Tencent", PositionName: "Backend", Status: "applied", Source: "test",
		AppliedAt: time.Date(2026, 7, 1, 9, 0, 0, 0, time.UTC),
	}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	for i := 0; i < 31; i++ {
		scheduledAt := time.Date(2026, 7, i+1, 14, 0, 0, 0, time.UTC)
		duration := "60m"
		if i == 0 {
			duration = "60"
		}
		if i == 2 {
			duration = ""
		}
		if err := d.CreateEvent(&db.Event{
			ApplicationID: app.ID,
			EventType:     "interview",
			ScheduledAt:   &scheduledAt,
			Duration:      duration,
		}); err != nil {
			t.Fatalf("create event %d: %v", i, err)
		}
	}

	summary := BuildDataSummary(d)
	if strings.Count(summary, "interview") != 30 {
		t.Fatalf("summary should include first 30 events, got %d in %s", strings.Count(summary, "interview"), summary)
	}
	if !strings.Contains(summary, "其余 1") {
		t.Fatalf("summary missing event truncation line: %s", summary)
	}
	if !strings.Contains(summary, "时长60分钟") {
		t.Fatalf("summary should render numeric duration in minutes: %s", summary)
	}
	if strings.Contains(summary, "60m分钟") {
		t.Fatalf("summary should not duplicate duration units: %s", summary)
	}
	if strings.Contains(summary, "2026-07-03 14:00 时长") {
		t.Fatalf("summary should omit empty durations: %s", summary)
	}
}
