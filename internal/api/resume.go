package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/config"
	"github.com/offercontext/offerpilot/internal/db"
	"github.com/offercontext/offerpilot/internal/resume"
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
	r.Post("/resumes/upload", uploadResumeHandler(database, dataDir))
	r.Put("/resumes/{id}/text", updateResumeTextHandler(database))
	r.Get("/resumes/{id}/file", downloadResumeFileHandler(database, dataDir))
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

const (
	maxResumeUploadBytes        = 10 << 20 // 10 MB
	maxResumeUploadRequestBytes = maxResumeUploadBytes + 64*1024
)

func uploadResumeHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, maxResumeUploadRequestBytes)
		reader, err := r.MultipartReader()
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid multipart form")
			return
		}
		var filename string
		var data []byte
		var fileSeen bool
		for {
			part, err := reader.NextPart()
			if errors.Is(err, io.EOF) {
				break
			}
			if isMaxBytesError(err) {
				respondError(w, http.StatusBadRequest, "request is too large")
				return
			}
			if err != nil {
				respondError(w, http.StatusBadRequest, "Invalid multipart form")
				return
			}
			if part.FormName() != "file" {
				part.Close()
				continue
			}
			if fileSeen {
				respondError(w, http.StatusBadRequest, "only one file is supported")
				return
			}
			fileSeen = true
			filename = part.FileName()
			if filename == "" {
				part.Close()
				respondError(w, http.StatusBadRequest, "file is required")
				return
			}
			if strings.ToLower(filepath.Ext(filename)) != ".pdf" {
				part.Close()
				respondError(w, http.StatusBadRequest, "only .pdf files are supported")
				return
			}
			data, err = io.ReadAll(io.LimitReader(part, maxResumeUploadBytes+1))
			if closeErr := part.Close(); err == nil {
				err = closeErr
			}
			if isMaxBytesError(err) {
				respondError(w, http.StatusBadRequest, "request is too large")
				return
			}
			if err != nil {
				respondError(w, http.StatusInternalServerError, err.Error())
				return
			}
		}
		if !fileSeen {
			respondError(w, http.StatusBadRequest, "file is required")
			return
		}
		if len(data) > maxResumeUploadBytes {
			respondError(w, http.StatusBadRequest, "file is too large")
			return
		}

		baseName := strings.TrimSuffix(filepath.Base(filename), filepath.Ext(filename))
		status := "parse-failed"
		parsed, _ := resume.ExtractPDFText(data)
		if strings.TrimSpace(parsed) != "" {
			status = "text-ready"
		}

		res := &db.Resume{
			Name:        baseName,
			ParsedData:  parsed,
			ParseStatus: status,
		}
		if err := database.CreateResume(res); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}

		// Persist original file (best-effort). If it fails the resume is still
		// usable via parsed_data; the download endpoint will 404 then.
		relPath := "resumes/" + strconv.FormatInt(res.ID, 10) + "_" + filepath.Base(filename)
		absPath := filepath.Join(dataDir, relPath)
		if err := os.MkdirAll(filepath.Dir(absPath), 0o755); err == nil {
			if werr := os.WriteFile(absPath, data, 0o644); werr == nil {
				_ = database.UpdateResumeFile(res.ID, relPath)
				res.FilePath = relPath
			}
		}

		respondJSON(w, http.StatusCreated, res)
	}
}

func updateResumeTextHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := resumeIDParam(w, r)
		if !ok {
			return
		}
		var req struct {
			Text string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		status := "parse-failed"
		if strings.TrimSpace(req.Text) != "" {
			status = "text-ready"
		}
		if err := database.UpdateResumeText(id, req.Text, status); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Updated"})
	}
}

func downloadResumeFileHandler(database *db.Database, dataDir string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := resumeIDParam(w, r)
		if !ok {
			return
		}
		res, err := database.GetResume(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Resume not found")
			return
		}
		if res.FilePath == "" {
			respondError(w, http.StatusNotFound, "resume has no original file")
			return
		}
		absPath := filepath.Join(dataDir, res.FilePath)
		if _, err := os.Stat(absPath); err != nil {
			respondError(w, http.StatusNotFound, "file not found on disk")
			return
		}
		w.Header().Set("Content-Disposition", `attachment; filename="`+filepath.Base(res.FilePath)+`"`)
		w.Header().Set("Content-Type", "application/pdf")
		http.ServeFile(w, r, absPath)
	}
}

func resumeIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}

func isMaxBytesError(err error) bool {
	var maxBytesErr *http.MaxBytesError
	return errors.As(err, &maxBytesErr)
}
