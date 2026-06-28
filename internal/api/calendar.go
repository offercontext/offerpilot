package api

import (
	"net/http"
	"time"

	"github.com/offercontext/offerpilot/internal/db"
)

// CalendarEntry is a single dated anchor in the calendar view.
type CalendarEntry struct {
	Date     string `json:"date"`            // YYYY-MM-DD
	Type     string `json:"type"`            // interview | applied
	Title    string `json:"title"`
	Subtitle string `json:"subtitle,omitempty"`
	AppID    int64  `json:"app_id"`
	NoteID   *int64 `json:"note_id,omitempty"`
}

// getCalendarHandler aggregates interview retrospective notes and applied_at
// dates into a flat list of calendar entries, filtered to the requested month.
//
// month query param is "YYYY-MM" (defaults to current month). Notes with
// unparseable date strings are silently skipped — the date field is freeform
// text and we don't want to crash the calendar on a typo.
func getCalendarHandler(database *db.Database) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		monthStr := r.URL.Query().Get("month")
		month, err := time.Parse("2006-01", monthStr)
		if err != nil {
			// Default to current month on bad/missing input.
			now := time.Now()
			month = time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
		}
		// Month bounds (UTC, matches how we store applied_at).
		start := month
		end := month.AddDate(0, 1, 0)

		var entries []CalendarEntry

		// 1. Interview retrospective notes (date is a freeform string; parse).
		if notes, nerr := database.ListInterviewNotes(0); nerr == nil {
			for _, n := range notes {
				t, perr := time.Parse("2006-01-02", n.Date)
				if perr != nil {
					continue // skip unparseable dates
				}
				t = t.UTC()
				if t.Before(start) || !t.Before(end) {
					continue
				}
				title := n.Company
				if n.Round != "" {
					title = n.Company + " · " + n.Round
				}
				entries = append(entries, CalendarEntry{
					Date:     t.Format("2006-01-02"),
					Type:     "interview",
					Title:    title,
					Subtitle: n.Position,
					AppID:    appIDOrZero(n.ApplicationID),
					NoteID:   &n.ID,
				})
			}
		}

		// 2. Applications by applied_at.
		if apps, aerr := database.ListApplications(""); aerr == nil {
			for i := range apps {
				a := &apps[i]
				t := a.AppliedAt.UTC()
				if t.Before(start) || !t.Before(end) {
					continue
				}
				entries = append(entries, CalendarEntry{
					Date:  t.Format("2006-01-02"),
					Type:  "applied",
					Title: a.CompanyName + " · " + a.PositionName,
					AppID: a.ID,
				})
			}
		}

		respondJSON(w, http.StatusOK, entries)
	}
}

// appIDOrZero dereferences a *int64 safely (0 means "unlinked").
func appIDOrZero(p *int64) int64 {
	if p == nil {
		return 0
	}
	return *p
}