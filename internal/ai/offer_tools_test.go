package ai

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func offerToolTestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/offer_tools.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func itoa(n int64) string {
	return strconv.FormatInt(n, 10)
}

func TestOfferToolsReadAndWrite(t *testing.T) {
	d := offerToolTestDB(t)
	o := &db.Offer{CompanyName: "字节", PositionName: "后端", BaseMonthly: 35000, MonthsPerYear: 16}
	if err := d.CreateOffer(o); err != nil {
		t.Fatalf("seed offer: %v", err)
	}
	reg := NewRegistry(d)

	if _, ok := reg.Get("list_offers"); !ok {
		t.Fatal("list_offers not registered")
	}
	out, err := reg.Execute(context.Background(), "list_offers", json.RawMessage(`{}`))
	if err != nil {
		t.Fatalf("list_offers: %v", err)
	}
	if !strings.Contains(out, "字节") {
		t.Fatalf("expected offer in list, got %s", out)
	}

	miss, err := reg.Execute(context.Background(), "get_offer", json.RawMessage(`{"id":9999}`))
	if err != nil {
		t.Fatalf("get_offer missing err: %v", err)
	}
	if !strings.Contains(miss, "未找到") {
		t.Fatalf("expected 未找到, got %s", miss)
	}

	tool, _ := reg.Get("update_offer")
	if !tool.Write {
		t.Fatal("update_offer must be a write tool")
	}
	upd := json.RawMessage(`{"id":` + itoa(o.ID) + `,"status":"accepted"}`)
	if _, err := reg.Execute(context.Background(), "update_offer", upd); err != nil {
		t.Fatalf("update_offer: %v", err)
	}
	got, _ := d.GetOffer(o.ID)
	if got.Status != "accepted" {
		t.Fatalf("expected accepted, got %s", got.Status)
	}

	asmt := json.RawMessage(`{"id":` + itoa(o.ID) + `,"assessment":"{\"level\":\"高于市场\"}"}`)
	if _, err := reg.Execute(context.Background(), "save_offer_assessment", asmt); err != nil {
		t.Fatalf("save_offer_assessment: %v", err)
	}
	got2, _ := d.GetOffer(o.ID)
	if !strings.Contains(got2.Assessment, "高于市场") {
		t.Fatalf("assessment not saved: %s", got2.Assessment)
	}
}
