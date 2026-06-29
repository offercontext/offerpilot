package db

import (
	"database/sql"
	"time"
)

// EventFilter filters event listings.
type EventFilter struct {
	Month         string
	ApplicationID int64
	EventType     string
	Start         *time.Time
	End           *time.Time
}

// EventWithApplication includes the application display fields for an event.
type EventWithApplication struct {
	Event
	CompanyName  string
	PositionName string
}

// CreateEvent inserts a new schedule event.
func (db *Database) CreateEvent(event *Event) error {
	res, err := db.conn.Exec(
		`INSERT INTO events (application_id, event_type, round, scheduled_at, duration, location, notes) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		event.ApplicationID, event.EventType, event.Round, nullableTime(event.ScheduledAt), event.Duration, event.Location, event.Notes,
	)
	if err != nil {
		return err
	}
	event.ID, _ = res.LastInsertId()
	event.CreatedAt = time.Now()
	return nil
}

// GetEvent retrieves a single event by ID.
func (db *Database) GetEvent(id int64) (*Event, error) {
	var event Event
	var scheduledAt sql.NullTime
	err := db.conn.QueryRow(
		`SELECT id, application_id, event_type, round, scheduled_at, duration, location, notes, created_at FROM events WHERE id = ?`, id,
	).Scan(&event.ID, &event.ApplicationID, &event.EventType, &event.Round, &scheduledAt, &event.Duration, &event.Location, &event.Notes, &event.CreatedAt)
	if err != nil {
		return nil, err
	}
	event.ScheduledAt = timePtrFromNull(scheduledAt)
	return &event, nil
}

// ListEvents lists events joined with their application display fields.
func (db *Database) ListEvents(filter EventFilter) ([]EventWithApplication, error) {
	query := `SELECT e.id, e.application_id, e.event_type, e.round, e.scheduled_at, e.duration, e.location, e.notes, e.created_at, a.company_name, a.position_name
		FROM events e
		JOIN applications a ON a.id = e.application_id`
	var args []interface{}
	var where []string

	if filter.Month != "" {
		start, err := time.Parse("2006-01", filter.Month)
		if err != nil {
			return nil, err
		}
		end := start.AddDate(0, 1, 0)
		where = append(where, "e.scheduled_at >= ? AND e.scheduled_at < ?")
		args = append(args, start, end)
	}
	if filter.ApplicationID > 0 {
		where = append(where, "e.application_id = ?")
		args = append(args, filter.ApplicationID)
	}
	if filter.EventType != "" {
		where = append(where, "e.event_type = ?")
		args = append(args, filter.EventType)
	}
	if filter.Start != nil {
		where = append(where, "e.scheduled_at >= ?")
		args = append(args, *filter.Start)
	}
	if filter.End != nil {
		where = append(where, "e.scheduled_at < ?")
		args = append(args, *filter.End)
	}
	for i, clause := range where {
		if i == 0 {
			query += " WHERE "
		} else {
			query += " AND "
		}
		query += clause
	}
	query += ` ORDER BY e.scheduled_at ASC, e.id ASC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []EventWithApplication
	for rows.Next() {
		var event EventWithApplication
		var scheduledAt sql.NullTime
		if err := rows.Scan(&event.ID, &event.ApplicationID, &event.EventType, &event.Round, &scheduledAt, &event.Duration, &event.Location, &event.Notes, &event.CreatedAt, &event.CompanyName, &event.PositionName); err != nil {
			return nil, err
		}
		event.ScheduledAt = timePtrFromNull(scheduledAt)
		out = append(out, event)
	}
	return out, rows.Err()
}

// ListEventsByApplication lists all events for a single application.
func (db *Database) ListEventsByApplication(applicationID int64) ([]EventWithApplication, error) {
	return db.ListEvents(EventFilter{ApplicationID: applicationID})
}

// UpdateEvent updates an existing schedule event.
func (db *Database) UpdateEvent(event *Event) error {
	res, err := db.conn.Exec(
		`UPDATE events SET application_id = ?, event_type = ?, round = ?, scheduled_at = ?, duration = ?, location = ?, notes = ? WHERE id = ?`,
		event.ApplicationID, event.EventType, event.Round, nullableTime(event.ScheduledAt), event.Duration, event.Location, event.Notes, event.ID,
	)
	if err != nil {
		return err
	}
	return errNoRowsWhenUnchanged(res)
}

// DeleteEvent removes an event by ID.
func (db *Database) DeleteEvent(id int64) error {
	res, err := db.conn.Exec(`DELETE FROM events WHERE id = ?`, id)
	if err != nil {
		return err
	}
	return errNoRowsWhenUnchanged(res)
}

func nullableTime(v *time.Time) interface{} {
	if v == nil {
		return nil
	}
	return *v
}

func timePtrFromNull(v sql.NullTime) *time.Time {
	if !v.Valid {
		return nil
	}
	t := v.Time
	return &t
}

func errNoRowsWhenUnchanged(res sql.Result) error {
	affected, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if affected == 0 {
		return sql.ErrNoRows
	}
	return nil
}
