package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
)

type generateMaterialKitRequest struct {
	ResumeID     *int64 `json:"resume_id,omitempty"`
	JDAnalysisID *int64 `json:"jd_analysis_id,omitempty"`
	JDText       string `json:"jd_text"`
	Overwrite    bool   `json:"overwrite"`
}

type updateMaterialKitRequest struct {
	ResumeID     *int64          `json:"resume_id,omitempty"`
	JDAnalysisID *int64          `json:"jd_analysis_id,omitempty"`
	JDSnapshot   *string         `json:"jd_snapshot,omitempty"`
	Status       string          `json:"status"`
	ContentJSON  json.RawMessage `json:"content_json"`
}

func registerMaterialKitRoutes(r chi.Router, database *db.Database, dataDir string) {
	r.Get("/applications/{id}/material-kit", getApplicationMaterialKitHandler(database))
	r.Post("/applications/{id}/material-kit/generate", generateApplicationMaterialKitHandler(database, dataDir))
	r.Put("/material-kits/{id}", updateMaterialKitHandler(database))
}

func getApplicationMaterialKitHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, ok := applicationIDParam(w, r)
		if !ok {
			return
		}
		kit, err := database.GetApplicationMaterialKitByApplication(appID)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Material kit not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, kit)
	}
}

func updateMaterialKitHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := materialKitIDParam(w, r)
		if !ok {
			return
		}
		var req updateMaterialKitRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		kit, err := database.GetApplicationMaterialKit(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Material kit not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if req.Status != "" {
			kit.Status = req.Status
		}
		if req.JDSnapshot != nil {
			kit.JDSnapshot = *req.JDSnapshot
		}
		if req.ResumeID != nil {
			kit.ResumeID = req.ResumeID
		}
		if req.JDAnalysisID != nil {
			kit.JDAnalysisID = req.JDAnalysisID
		}
		if len(req.ContentJSON) > 0 {
			content, ok := compactJSON(w, req.ContentJSON, "content_json must be valid JSON")
			if !ok {
				return
			}
			kit.ContentJSON = content
		}
		if err := database.UpdateApplicationMaterialKit(kit); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Material kit not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, kit)
	}
}

func generateApplicationMaterialKitHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, ok := applicationIDParam(w, r)
		if !ok {
			return
		}
		var req generateMaterialKitRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		if req.ResumeID == nil || *req.ResumeID <= 0 {
			respondError(w, http.StatusBadRequest, "resume_id is required")
			return
		}
		if strings.TrimSpace(req.JDText) == "" {
			respondError(w, http.StatusBadRequest, "jd_text is required")
			return
		}

		existing, err := database.GetApplicationMaterialKitByApplication(appID)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if existing != nil && !req.Overwrite {
			respondError(w, http.StatusConflict, "Material kit already exists")
			return
		}

		app, err := database.GetApplication(appID)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Application not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		resume, err := database.GetResume(*req.ResumeID)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		if strings.TrimSpace(resume.ParsedData) == "" {
			respondError(w, http.StatusBadRequest, "Resume has no text content")
			return
		}
		if req.JDAnalysisID != nil {
			if _, err := database.GetJDAnalysis(*req.JDAnalysisID); errors.Is(err, sql.ErrNoRows) {
				respondError(w, http.StatusNotFound, "JD analysis not found")
				return
			} else if err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
		}

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
		result, err := ai.GenerateMaterialKit(r.Context(), client, app.CompanyName, app.PositionName, resume.ParsedData, req.JDText)
		if err != nil {
			respondError(w, http.StatusBadGateway, err.Error())
			return
		}

		kit := existing
		if kit == nil {
			kit = &db.ApplicationMaterialKit{ApplicationID: appID}
		}
		kit.ResumeID = req.ResumeID
		kit.JDAnalysisID = req.JDAnalysisID
		kit.JDSnapshot = req.JDText
		kit.Status = "ready"
		kit.ContentJSON = ai.MarshalMaterialKit(result)
		if kit.ID == 0 {
			if err := database.CreateApplicationMaterialKit(kit); err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
			respondJSON(w, http.StatusCreated, kit)
			return
		}
		if err := database.UpdateApplicationMaterialKit(kit); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, kit)
	}
}

func compactJSON(w http.ResponseWriter, raw json.RawMessage, msg string) (string, bool) {
	if !json.Valid(raw) {
		respondError(w, http.StatusBadRequest, msg)
		return "", false
	}
	var v interface{}
	if err := json.Unmarshal(raw, &v); err != nil {
		respondError(w, http.StatusBadRequest, msg)
		return "", false
	}
	b, err := json.Marshal(v)
	if err != nil {
		respondError(w, http.StatusBadRequest, msg)
		return "", false
	}
	return string(b), true
}

func applicationIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}

func materialKitIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}
