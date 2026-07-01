package ai

import (
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestNegoCoachPromptEmbedsOffer(t *testing.T) {
	offer := &db.Offer{
		CompanyName: "字节跳动", PositionName: "后端开发", Status: "negotiating",
		BaseMonthly: 35000, MonthsPerYear: 16, SigningBonus: 50000, Equity: "20万股/4年",
	}
	p := NegoCoachPrompt(offer, "面试复盘：算法轮表现优秀")

	for _, want := range []string{"谈薪教练", "字节跳动", "后端开发", "35000", "16", "50000", "20万股/4年", "面试复盘：算法轮表现优秀", "安全红线", "反问询价"} {
		if !strings.Contains(p, want) {
			t.Fatalf("prompt missing %q\n---\n%s", want, p)
		}
	}
	if !strings.Contains(p, "610000") {
		t.Fatalf("prompt missing derived total cash 610000\n%s", p)
	}
}

func TestNegoCoachPromptNilOffer(t *testing.T) {
	p := NegoCoachPrompt(nil, "")
	if !strings.Contains(p, "谈薪教练") {
		t.Fatal("base prompt missing")
	}
	if strings.Contains(p, "当前 offer 快照") {
		t.Fatal("should not include offer snapshot when offer is nil")
	}
}
