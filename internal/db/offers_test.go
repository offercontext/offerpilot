package db

import "testing"

func TestOfferCRUD(t *testing.T) {
	d := newTestDB(t)

	o := &Offer{CompanyName: "字节跳动", PositionName: "后端", BaseMonthly: 35000, MonthsPerYear: 16, SigningBonus: 50000}
	if err := d.CreateOffer(o); err != nil {
		t.Fatalf("create offer: %v", err)
	}
	if o.ID == 0 {
		t.Fatal("expected non-zero id")
	}
	if o.Status != "pending" {
		t.Fatalf("expected default status pending, got %q", o.Status)
	}
	if o.TotalCash != 35000*16+50000 {
		t.Fatalf("expected total_cash %d, got %d", 35000*16+50000, o.TotalCash)
	}

	got, err := d.GetOffer(o.ID)
	if err != nil {
		t.Fatalf("get offer: %v", err)
	}
	if got.CompanyName != "字节跳动" || got.TotalCash != o.TotalCash {
		t.Fatalf("unexpected offer: %+v", got)
	}

	got.Status = "accepted"
	got.BaseMonthly = 38000
	if err := d.UpdateOffer(got); err != nil {
		t.Fatalf("update offer: %v", err)
	}
	if got.TotalCash != 38000*16+50000 {
		t.Fatalf("total_cash not recomputed: %d", got.TotalCash)
	}
	reloaded, err := d.GetOffer(got.ID)
	if err != nil {
		t.Fatalf("reload offer: %v", err)
	}
	if reloaded.BaseMonthly != 38000 || reloaded.Status != "accepted" || reloaded.TotalCash != 38000*16+50000 {
		t.Fatalf("update not persisted: %+v", reloaded)
	}

	all, err := d.ListOffers("")
	if err != nil || len(all) != 1 {
		t.Fatalf("list all: %v len=%d", err, len(all))
	}
	accepted, err := d.ListOffers("accepted")
	if err != nil || len(accepted) != 1 {
		t.Fatalf("list accepted: %v len=%d", err, len(accepted))
	}
	none, _ := d.ListOffers("pending")
	if len(none) != 0 {
		t.Fatalf("expected 0 pending, got %d", len(none))
	}

	if err := d.DeleteOffer(o.ID); err != nil {
		t.Fatalf("delete offer: %v", err)
	}
	remaining, _ := d.ListOffers("")
	if len(remaining) != 0 {
		t.Fatalf("expected 0 after delete, got %d", len(remaining))
	}
}

func TestOfferApplicationSetNullOnDelete(t *testing.T) {
	d := newTestDB(t)
	app := &Application{CompanyName: "腾讯", PositionName: "后端", Status: "offer", Source: "test"}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create app: %v", err)
	}
	o := &Offer{CompanyName: "腾讯", PositionName: "后端", ApplicationID: &app.ID, BaseMonthly: 40000, MonthsPerYear: 14}
	if err := d.CreateOffer(o); err != nil {
		t.Fatalf("create offer: %v", err)
	}
	if err := d.DeleteApplication(app.ID); err != nil {
		t.Fatalf("delete app: %v", err)
	}
	got, err := d.GetOffer(o.ID)
	if err != nil {
		t.Fatalf("get offer: %v", err)
	}
	if got.ApplicationID != nil {
		t.Fatalf("expected application_id to be NULL after app delete, got %v", *got.ApplicationID)
	}
}
