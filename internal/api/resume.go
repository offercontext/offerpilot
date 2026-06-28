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

// createResumeRequest — POST /api/resumes (paste text).
type createResumeRequest struct {
	Name string `json:"name"`
	Text string `json:"text"`
}

// matchResumeRequest — POST /api/resumes/{id}/match.
type matchResumeRequest struct {
	JDText        string `json:"jd_text"`
	JDURL         string `json:"jd_url"`
	ApplicationID *int64 `json:"application_id,omitempty"`
}

func registerResumeRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Post("/resumes", createResumeHandler(database))
	r.Get("/resumes", listResumesHandler(database))
	r.Get("/resumes/{id}", getResumeHandler(database))
	r.Delete("/resumes/{id}", deleteResumeHandler(database))
	r.Post("/resumes/{id}/match", matchResumeHandler(database, dataDir))
	r.Get("/resumes/{id}/matches", listResumeMatchesHandler(database))
}

func createResumeHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req createResumeRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		if req.Text == "" {
			respondError(w, http.StatusBadRequest, "text is required")
			return
		}
		res := &db.Resume{
			Name:        req.Name,
			ParsedData:  req.Text,
			ParseStatus: "text-ready",
		}
		if err := database.CreateResume(res); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, res)
	}
}

func listResumesHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		resumes, err := database.ListResumes()
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, resumes)
	}
}

func getResumeHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		res, err := database.GetResume(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		}
		respondJSON(w, http.StatusOK, res)
	}
}

func deleteResumeHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		if err := database.DeleteResume(id); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

func matchResumeHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		var req matchResumeRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}

		// Load resume text.
		resume, err := database.GetResume(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		}
		if resume.ParsedData == "" {
			respondError(w, http.StatusBadRequest, "Resume has no text content")
			return
		}

		// Resolve JD text.
		jdText := req.JDText
		if jdText == "" && req.JDURL != "" {
			fetched, ferr := ai.FetchJDFromURL(req.JDURL)
			if ferr != nil {
				respondError(w, http.StatusBadRequest, ferr.Error())
				return
			}
			jdText = fetched
		}
		if jdText == "" {
			respondError(w, http.StatusBadRequest, "jd_text or jd_url is required")
			return
		}

		// AI client.
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

		result, err := ai.MatchResume(r.Context(), client, resume.ParsedData, jdText)
		if err != nil {
			respondError(w, http.StatusBadGateway, err.Error())
			return
		}
		rec, err := ai.PersistResumeMatch(database, id, req.ApplicationID, jdText, ai.MarshalMatch(result))
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, map[string]interface{}{
			"id":             rec.ID,
			"resume_id":      id,
			"application_id": req.ApplicationID,
			"result":         result,
		})
	}
}

func listResumeMatchesHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		matches, err := database.ListResumeMatches(id)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, matches)
	}
}