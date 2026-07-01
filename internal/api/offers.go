package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

type offerRequest struct {
	ApplicationID *int64 `json:"application_id,omitempty"`
	CompanyName   string `json:"company_name"`
	PositionName  string `json:"position_name"`
	Status        string `json:"status"`
	BaseMonthly   int64  `json:"base_monthly"`
	MonthsPerYear int64  `json:"months_per_year"`
	SigningBonus  int64  `json:"signing_bonus"`
	Equity        string `json:"equity"`
	Perks         string `json:"perks"`
	Deadline      string `json:"deadline"`
	Notes         string `json:"notes"`
	Assessment    string `json:"assessment"`
}

var validOfferStatus = map[string]bool{
	"pending": true, "negotiating": true, "accepted": true, "declined": true, "expired": true,
}

func registerOfferRoutes(r chi.Router, database *db.Database) {
	r.Get("/offers", listOffersHandler(database))
	r.Post("/offers", createOfferHandler(database))
	r.Get("/offers/compare", compareOffersHandler(database))
	r.Get("/offers/{id}", getOfferHandler(database))
	r.Put("/offers/{id}", updateOfferHandler(database))
	r.Delete("/offers/{id}", deleteOfferHandler(database))
}

// validateOfferRequest checks required + range constraints. Returns error message ("" = ok).
func validateOfferRequest(req offerRequest) string {
	if strings.TrimSpace(req.CompanyName) == "" {
		return "company_name is required"
	}
	if strings.TrimSpace(req.PositionName) == "" {
		return "position_name is required"
	}
	if req.BaseMonthly < 0 || req.SigningBonus < 0 {
		return "base_monthly and signing_bonus must be non-negative"
	}
	if req.MonthsPerYear < 1 {
		return "months_per_year must be at least 1"
	}
	if req.Status != "" && !validOfferStatus[req.Status] {
		return "invalid status"
	}
	return ""
}

func listOffersHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		status := r.URL.Query().Get("status")
		offers, err := database.ListOffers(status)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, offers)
	}
}

func createOfferHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req offerRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		if req.MonthsPerYear == 0 {
			req.MonthsPerYear = 12
		}
		if msg := validateOfferRequest(req); msg != "" {
			respondError(w, http.StatusUnprocessableEntity, msg)
			return
		}
		if req.ApplicationID != nil {
			if *req.ApplicationID <= 0 {
				respondError(w, http.StatusUnprocessableEntity, "invalid application_id")
				return
			}
			if _, err := database.GetApplication(*req.ApplicationID); errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusUnprocessableEntity, "application not found")
				return
			} else if err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
		}
		o := &db.Offer{
			ApplicationID: req.ApplicationID, CompanyName: req.CompanyName, PositionName: req.PositionName,
			Status: req.Status, BaseMonthly: req.BaseMonthly, MonthsPerYear: req.MonthsPerYear,
			SigningBonus: req.SigningBonus, Equity: req.Equity, Perks: req.Perks,
			Deadline: req.Deadline, Notes: req.Notes, Assessment: req.Assessment,
		}
		if err := database.CreateOffer(o); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, o)
	}
}

func getOfferHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid offer ID")
			return
		}
		o, err := database.GetOffer(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "offer not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, o)
	}
}

func updateOfferHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid offer ID")
			return
		}
		existing, err := database.GetOffer(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "offer not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		var req offerRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		if req.MonthsPerYear == 0 {
			req.MonthsPerYear = existing.MonthsPerYear
		}
		if msg := validateOfferRequest(req); msg != "" {
			respondError(w, http.StatusUnprocessableEntity, msg)
			return
		}
		// id and application_id are immutable; keep existing binding.
		existing.CompanyName = req.CompanyName
		existing.PositionName = req.PositionName
		existing.Status = req.Status
		existing.BaseMonthly = req.BaseMonthly
		existing.MonthsPerYear = req.MonthsPerYear
		existing.SigningBonus = req.SigningBonus
		existing.Equity = req.Equity
		existing.Perks = req.Perks
		existing.Deadline = req.Deadline
		existing.Notes = req.Notes
		existing.Assessment = req.Assessment
		if existing.Status == "" {
			existing.Status = "pending"
		}
		if err := database.UpdateOffer(existing); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, existing)
	}
}

func deleteOfferHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "invalid offer ID")
			return
		}
		if err := database.DeleteOffer(id); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
	}
}

// compareOffersHandler returns the offers named by ?ids=1,2,3 in request order.
func compareOffersHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		raw := r.URL.Query().Get("ids")
		if raw == "" {
			respondError(w, http.StatusBadRequest, "ids query param is required")
			return
		}
		var offers []db.Offer
		for _, part := range strings.Split(raw, ",") {
			part = strings.TrimSpace(part)
			if part == "" {
				continue
			}
			id, err := strconv.ParseInt(part, 10, 64)
			if err != nil {
				respondError(w, http.StatusBadRequest, "invalid id in ids: "+part)
				return
			}
			o, err := database.GetOffer(id)
			if errors.Is(err, sql.ErrNoRows) {
				continue
			}
			if err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
			offers = append(offers, *o)
		}
		respondJSON(w, http.StatusOK, offers)
	}
}
