package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

// analyzeJDRequest is the body for POST /api/jd/analyze.
type analyzeJDRequest struct {
	JDText       string `json:"jd_text"`
	JDURL        string `json:"jd_url"`
	ApplicationID *int64 `json:"application_id,omitempty"`
}

// registerJDRoutes wires the JD analysis endpoints onto the /api group.
func registerJDRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Post("/jd/analyze", analyzeJDHandler(database, dataDir))
	r.Get("/jd/analyses", listJDAnalysesHandler(database))
	r.Get("/jd/analyses/{id}", getJDAnalysisHandler(database))
}

// analyzeJDHandler runs an AI JD analysis and persists the result.
func analyzeJDHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req analyzeJDRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		// Resolve JD text: explicit text wins, otherwise fetch from URL.
		jdText := req.JDText
		source := "text"
		if jdText == "" && req.JDURL != "" {
			fetched, err := ai.FetchJDFromURL(req.JDURL)
			if err != nil {
				respondError(w, http.StatusBadRequest, err.Error())
				return
			}
			jdText = fetched
			source = "url"
		}
		if jdText == "" {
			respondError(w, http.StatusBadRequest, "jd_text or jd_url is required")
			return
		}

		// Build AI client from config; absence of key returns a clear error.
		cfg, err := config.Load(dataDir)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		client, err := ai.New(cfg)
		if err != nil {
			respondError(w, http.StatusServiceUnavailable, err.Error())
			return
		}

		result, err := ai.AnalyzeJD(r.Context(), client, jdText)
		if err != nil {
			respondError(w, http.StatusBadGateway, err.Error())
			return
		}
		resultJSON, _ := json.Marshal(result)
		rec, err := ai.PersistJDAnalysis(database, req.ApplicationID, source, jdText, string(resultJSON))
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, map[string]interface{}{
			"id":          rec.ID,
			"application_id": req.ApplicationID,
			"jd_source":   source,
			"result":      result,
		})
	}
}

// listJDAnalysesHandler returns all stored JD analyses (optionally filtered by ?application_id=).
func listJDAnalysesHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID := int64(0)
		if v := r.URL.Query().Get("application_id"); v != "" {
			if id, err := strconv.ParseInt(v, 10, 64); err == nil {
				appID = id
			}
		}
		analyses, err := database.ListJDAnalyses(appID)
		if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to list JD analyses")
			return
		}
		respondJSON(w, http.StatusOK, analyses)
	}
}

// getJDAnalysisHandler returns a single JD analysis by ID.
func getJDAnalysisHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		a, err := database.GetJDAnalysis(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "JD analysis not found")
			return
		}
		respondJSON(w, http.StatusOK, a)
	}
}