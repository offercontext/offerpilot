package ai

import (
	"strings"
	"testing"

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
