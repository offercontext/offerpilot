package api

import (
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

// listApplications returns all applications, optionally filtered by status
func listApplications(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		status := r.URL.Query().Get("status")
		apps, err := database.ListApplications(status)
		if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to list applications")
			return
		}
		respondJSON(w, http.StatusOK, apps)
	}
}

// createApplication adds a new application
func createApplication(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var app db.Application
		if err := json.NewDecoder(r.Body).Decode(&app); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		if app.CompanyName == "" || app.PositionName == "" {
			respondError(w, http.StatusBadRequest, "company_name and position_name are required")
			return
		}
		if app.Status == "" {
			app.Status = "applied"
		}
		if app.Source == "" {
			app.Source = "web"
		}
		app.AppliedAt = time.Now()

		if err := database.CreateApplication(&app); err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to create application")
			return
		}
		respondJSON(w, http.StatusCreated, app)
	}
}

// getApplication returns a single application by ID
func getApplication(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		app, err := database.GetApplication(id)
		if err != nil {
			respondError(w, http.StatusNotFound, "Application not found")
			return
		}
		respondJSON(w, http.StatusOK, app)
	}
}

// updateApplication updates an application
func updateApplication(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		var app db.Application
		if err := json.NewDecoder(r.Body).Decode(&app); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid request body")
			return
		}
		app.ID = id
		if err := database.UpdateApplication(&app); err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to update application")
			return
		}
		respondJSON(w, http.StatusOK, app)
	}
}

// deleteApplication removes an application
func deleteApplication(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
		if err != nil {
			respondError(w, http.StatusBadRequest, "Invalid ID")
			return
		}
		if err := database.DeleteApplication(id); err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to delete application")
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

// getDashboard returns aggregated board data
func getDashboard(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		apps, err := database.ListApplications("")
		if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to load dashboard")
			return
		}

		// Group by status
		board := make(map[string][]db.Application)
		for _, app := range apps {
			board[app.Status] = append(board[app.Status], app)
		}

		respondJSON(w, http.StatusOK, map[string]interface{}{
			"total":   len(apps),
			"board":   board,
		})
	}
}