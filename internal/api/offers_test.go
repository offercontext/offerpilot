package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func offerTestRouter(t *testing.T) (*db.Database, http.Handler) {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/offers.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d, NewRouter(d, t.TempDir())
}

func offerReq(t *testing.T, router http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var reader *bytes.Reader
	if body != nil {
		data, _ := json.Marshal(body)
		reader = bytes.NewReader(data)
	} else {
		reader = bytes.NewReader(nil)
	}
	req := httptest.NewRequest(method, path, reader)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	return rec
}

func TestOfferAPICRUD(t *testing.T) {
	_, router := offerTestRouter(t)

	createBody := map[string]interface{}{
		"company_name": "字节", "position_name": "后端",
		"base_monthly": 35000, "months_per_year": 16, "signing_bonus": 50000,
	}
	rec := offerReq(t, router, http.MethodPost, "/api/offers", createBody)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create status %d: %s", rec.Code, rec.Body.String())
	}
	var created db.Offer
	json.Unmarshal(rec.Body.Bytes(), &created)
	if created.TotalCash != 35000*16+50000 {
		t.Fatalf("expected total_cash, got %d", created.TotalCash)
	}

	getRec := offerReq(t, router, http.MethodGet, "/api/offers/"+itoaAPI(created.ID), nil)
	if getRec.Code != http.StatusOK {
		t.Fatalf("get status %d", getRec.Code)
	}

	updBody := map[string]interface{}{"company_name": "字节", "position_name": "后端", "status": "accepted", "base_monthly": 38000, "months_per_year": 16, "signing_bonus": 50000}
	updRec := offerReq(t, router, http.MethodPut, "/api/offers/"+itoaAPI(created.ID), updBody)
	if updRec.Code != http.StatusOK {
		t.Fatalf("update status %d: %s", updRec.Code, updRec.Body.String())
	}
	var updated db.Offer
	json.Unmarshal(updRec.Body.Bytes(), &updated)
	if updated.Status != "accepted" || updated.TotalCash != 38000*16+50000 {
		t.Fatalf("unexpected updated offer: %+v", updated)
	}

	listRec := offerReq(t, router, http.MethodGet, "/api/offers", nil)
	var list []db.Offer
	json.Unmarshal(listRec.Body.Bytes(), &list)
	if len(list) != 1 {
		t.Fatalf("expected 1 offer, got %d", len(list))
	}

	delRec := offerReq(t, router, http.MethodDelete, "/api/offers/"+itoaAPI(created.ID), nil)
	if delRec.Code != http.StatusOK {
		t.Fatalf("delete status %d", delRec.Code)
	}
}

func TestOfferAPIValidation(t *testing.T) {
	_, router := offerTestRouter(t)

	rec := offerReq(t, router, http.MethodPost, "/api/offers", map[string]interface{}{"position_name": "后端", "months_per_year": 12})
	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for missing company, got %d", rec.Code)
	}

	rec2 := offerReq(t, router, http.MethodPost, "/api/offers", map[string]interface{}{"company_name": "字节", "position_name": "后端", "base_monthly": -1, "months_per_year": 12})
	if rec2.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for negative base, got %d", rec2.Code)
	}

	appID := int64(999)
	rec3 := offerReq(t, router, http.MethodPost, "/api/offers", map[string]interface{}{"company_name": "字节", "position_name": "后端", "months_per_year": 12, "application_id": appID})
	if rec3.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422 for missing app, got %d", rec3.Code)
	}
}

func TestOfferAPICompare(t *testing.T) {
	d, router := offerTestRouter(t)
	o1 := &db.Offer{CompanyName: "字节", PositionName: "后端", BaseMonthly: 35000, MonthsPerYear: 16}
	o2 := &db.Offer{CompanyName: "腾讯", PositionName: "后端", BaseMonthly: 40000, MonthsPerYear: 14}
	d.CreateOffer(o1)
	d.CreateOffer(o2)

	rec := offerReq(t, router, http.MethodGet, "/api/offers/compare?ids="+itoaAPI(o1.ID)+","+itoaAPI(o2.ID), nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("compare status %d: %s", rec.Code, rec.Body.String())
	}
	var offers []db.Offer
	json.Unmarshal(rec.Body.Bytes(), &offers)
	if len(offers) != 2 {
		t.Fatalf("expected 2 offers, got %d", len(offers))
	}

	bad := offerReq(t, router, http.MethodGet, "/api/offers/compare", nil)
	if bad.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for missing ids, got %d", bad.Code)
	}
}

func itoaAPI(n int64) string {
	return strconv.FormatInt(n, 10)
}
