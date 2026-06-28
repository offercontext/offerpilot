package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

type createNoteRequest struct {
	ApplicationID    *int64 `json:"application_id,omitempty"`
	Company          string `json:"company"`
	Position         string `json:"position"`
	Round            string `json:"round"`
	Date             string `json:"date"`
	Questions        string `json:"questions"`
	SelfReflection   string `json:"self_reflection"`
	DifficultyPoints string `json:"difficulty_points"`
	Mood             string `json:"mood"`
}

type updateNoteRequest = createNoteRequest

func registerNoteRoutes(r chi.Router, database *db.Database) {
	r.Get("/applications/{id}/notes", listNotesByAppHandler(database))
	r.Post("/applications/{id}/notes", createNoteForAppHandler(database))
	r.Put("/notes/{id}", updateNoteHandler(database))
	r.Delete("/notes/{id}", deleteNoteHandler(database))
	r.Get("/notes", listNotesHandler(database))
}

// listNotesByAppHandler returns notes linked to a given application (newest first).
func listNotesByAppHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid application ID")
			return
		}
		notes, err := database.ListInterviewNotes(appID)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, notes)
	}
}

// createNoteForAppHandler creates a note linked to the application in the URL.
// When company/position are blank they are filled from the application record.
func createNoteForAppHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		appID, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid application ID")
			return
		}
		var req createNoteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		// Backfill company/position from the application when omitted.
		if req.Company == "" || req.Position == "" {
			if app, aerr := database.GetApplication(appID); aerr == nil {
				if req.Company == "" {
					req.Company = app.CompanyName
				}
				if req.Position == "" {
					req.Position = app.PositionName
				}
			}
		}
		if req.Company == "" {
			respondError(w, http.StatusBadRequest, "company is required")
			return
		}
		n := &db.InterviewNote{
			ApplicationID:    &appID,
			Company:          req.Company,
			Position:         req.Position,
			Round:            req.Round,
			Date:             req.Date,
			Questions:        req.Questions,
			SelfReflection:   req.SelfReflection,
			DifficultyPoints: req.DifficultyPoints,
			Mood:             req.Mood,
		}
		if err := database.CreateInterviewNote(n); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusCreated, n)
	}
}

func listNotesHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		notes, err := database.ListInterviewNotes(0)
		if err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, notes)
	}
}

func updateNoteHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		var req updateNoteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		n := &db.InterviewNote{
			ID:               id,
			Company:          req.Company,
			Position:         req.Position,
			Round:            req.Round,
			Date:             req.Date,
			Questions:        req.Questions,
			SelfReflection:   req.SelfReflection,
			DifficultyPoints: req.DifficultyPoints,
			Mood:             req.Mood,
		}
		if err := database.UpdateInterviewNote(n); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, n)
	}
}

func deleteNoteHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		if err := database.DeleteInterviewNote(id); err != nil {
			respondError(w, http.StatusInternalServerError, err.Error())
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}