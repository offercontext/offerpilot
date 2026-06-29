package api

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/offercontext/offerpilot/internal/db"
)

type eventRequest struct {
	ApplicationID   int64  `json:"application_id"`
	EventType       string `json:"event_type"`
	Round           int    `json:"round"`
	ScheduledAt     string `json:"scheduled_at"`
	DurationMinutes int    `json:"duration_minutes"`
	Location        string `json:"location"`
	Notes           string `json:"notes"`
}

type eventResponse struct {
	ID              int64     `json:"id"`
	ApplicationID   int64     `json:"application_id"`
	EventType       string    `json:"event_type"`
	Round           int       `json:"round"`
	ScheduledAt     string    `json:"scheduled_at"`
	DurationMinutes int       `json:"duration_minutes"`
	Location        string    `json:"location"`
	Notes           string    `json:"notes"`
	CreatedAt       time.Time `json:"created_at"`
	CompanyName     string    `json:"company_name,omitempty"`
	PositionName    string    `json:"position_name,omitempty"`
}

func registerEventRoutes(r chi.Router, database *db.Database) {
	r.Get("/events", listEvents(database))
	r.Post("/events", createEvent(database))
	r.Get("/events/{id}", getEvent(database))
	r.Put("/events/{id}", updateEvent(database))
	r.Delete("/events/{id}", deleteEvent(database))
}

func listEvents(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		filter, ok := eventFilterFromRequest(w, r)
		if !ok {
			return
		}
		if filter.ApplicationID > 0 && !applicationExists(w, database, filter.ApplicationID) {
			return
		}
		events, err := database.ListEvents(filter)
		if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to list events")
			return
		}
		resp := make([]eventResponse, 0, len(events))
		for _, event := range events {
			resp = append(resp, eventWithApplicationResponse(event))
		}
		respondJSON(w, http.StatusOK, resp)
	}
}

func createEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		event, ok := decodeEventRequest(w, r)
		if !ok {
			return
		}
		if !applicationExists(w, database, event.ApplicationID) {
			return
		}
		if err := database.CreateEvent(event); err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to create event")
			return
		}
		respondJSON(w, http.StatusCreated, eventResponseFromEvent(*event))
	}
}

func getEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		event, err := database.GetEvent(id)
		if errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Event not found")
			return
		}
		if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to get event")
			return
		}
		respondJSON(w, http.StatusOK, eventResponseFromEvent(*event))
	}
}

func updateEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		if _, err := database.GetEvent(id); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Event not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to get event")
			return
		}
		event, ok := decodeEventRequest(w, r)
		if !ok {
			return
		}
		if !applicationExists(w, database, event.ApplicationID) {
			return
		}
		event.ID = id
		if err := database.UpdateEvent(event); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Event not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to update event")
			return
		}
		respondJSON(w, http.StatusOK, eventResponseFromEvent(*event))
	}
}

func deleteEvent(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := eventIDParam(w, r)
		if !ok {
			return
		}
		if err := database.DeleteEvent(id); errors.Is(err, sql.ErrNoRows) {
			respondError(w, http.StatusNotFound, "Event not found")
			return
		} else if err != nil {
			respondError(w, http.StatusInternalServerError, "Failed to delete event")
			return
		}
		respondJSON(w, http.StatusOK, map[string]string{"message": "Deleted"})
	}
}

func eventFilterFromRequest(w http.ResponseWriter, r *http.Request) (db.EventFilter, bool) {
	query := r.URL.Query()
	filter := db.EventFilter{Month: query.Get("month"), EventType: query.Get("type")}

	if filter.Month != "" {
		if _, err := time.Parse("2006-01", filter.Month); err != nil {
			respondError(w, http.StatusBadRequest, "Invalid month")
			return filter, false
		}
	}
	if filter.EventType != "" && !validEventType(filter.EventType) {
		respondError(w, http.StatusBadRequest, "Invalid event type")
		return filter, false
	}
	if rawID := query.Get("application_id"); rawID != "" {
		id, err := strconv.ParseInt(rawID, 10, 64)
		if err != nil || id <= 0 {
			respondError(w, http.StatusBadRequest, "Invalid application_id")
			return filter, false
		}
		filter.ApplicationID = id
	}
	return filter, true
}

func decodeEventRequest(w http.ResponseWriter, r *http.Request) (*db.Event, bool) {
	var req eventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respondError(w, http.StatusBadRequest, "Invalid request body")
		return nil, false
	}
	if !validEventType(req.EventType) {
		respondError(w, http.StatusBadRequest, "Invalid event type")
		return nil, false
	}
	if req.DurationMinutes <= 0 {
		respondError(w, http.StatusBadRequest, "duration_minutes must be greater than 0")
		return nil, false
	}
	if req.ScheduledAt == "" {
		respondError(w, http.StatusBadRequest, "scheduled_at is required")
		return nil, false
	}
	scheduledAt, err := time.Parse(time.RFC3339, req.ScheduledAt)
	if err != nil {
		respondError(w, http.StatusBadRequest, "scheduled_at must be RFC3339")
		return nil, false
	}
	return &db.Event{
		ApplicationID: req.ApplicationID,
		EventType:     req.EventType,
		Round:         req.Round,
		ScheduledAt:   &scheduledAt,
		Duration:      durationString(req.DurationMinutes),
		Location:      req.Location,
		Notes:         req.Notes,
	}, true
}

func validEventType(eventType string) bool {
	return eventType == "written_test" || eventType == "interview" || eventType == "assessment"
}

func eventIDParam(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(chi.URLParam(r, "id"), 10, 64)
	if err != nil || id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid ID")
		return 0, false
	}
	return id, true
}

func applicationExists(w http.ResponseWriter, database *db.Database, id int64) bool {
	if id <= 0 {
		respondError(w, http.StatusBadRequest, "Invalid application_id")
		return false
	}
	if _, err := database.GetApplication(id); errors.Is(err, sql.ErrNoRows) {
		respondError(w, http.StatusNotFound, "Application not found")
		return false
	} else if err != nil {
		respondError(w, http.StatusInternalServerError, "Failed to get application")
		return false
	}
	return true
}

func eventWithApplicationResponse(event db.EventWithApplication) eventResponse {
	resp := eventResponseFromEvent(event.Event)
	resp.CompanyName = event.CompanyName
	resp.PositionName = event.PositionName
	return resp
}

func eventResponseFromEvent(event db.Event) eventResponse {
	return eventResponse{
		ID:              event.ID,
		ApplicationID:   event.ApplicationID,
		EventType:       event.EventType,
		Round:           event.Round,
		ScheduledAt:     scheduledAtString(event.ScheduledAt),
		DurationMinutes: durationMinutes(event.Duration),
		Location:        event.Location,
		Notes:           event.Notes,
		CreatedAt:       event.CreatedAt,
	}
}

func scheduledAtString(scheduledAt *time.Time) string {
	if scheduledAt == nil {
		return ""
	}
	return scheduledAt.Format(time.RFC3339)
}

func durationString(minutes int) string {
	return strconv.Itoa(minutes) + "m"
}

func durationMinutes(duration string) int {
	minutes, _ := strconv.Atoi(strings.TrimSuffix(duration, "m"))
	return minutes
}
