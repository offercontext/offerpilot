package db

import (
	"database/sql"
	"time"
)

// CreateInterviewNote inserts an interview retrospective note.
func (db *Database) CreateInterviewNote(n *InterviewNote) error {
	res, err := db.conn.Exec(
		`INSERT INTO interview_notes (application_id, company, position, round, date, questions, self_reflection, difficulty_points, mood) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		nullableInt64(n.ApplicationID), n.Company, n.Position, n.Round, n.Date, n.Questions, n.SelfReflection, n.DifficultyPoints, n.Mood,
	)
	if err != nil {
		return err
	}
	n.ID, _ = res.LastInsertId()
	n.CreatedAt = time.Now()
	return nil
}

// GetInterviewNote retrieves a single note by ID.
func (db *Database) GetInterviewNote(id int64) (*InterviewNote, error) {
	var n InterviewNote
	var appID sql.NullInt64
	err := db.conn.QueryRow(
		`SELECT id, application_id, company, position, round, date, questions, self_reflection, difficulty_points, mood, created_at FROM interview_notes WHERE id = ?`, id,
	).Scan(&n.ID, &appID, &n.Company, &n.Position, &n.Round, &n.Date, &n.Questions, &n.SelfReflection, &n.DifficultyPoints, &n.Mood, &n.CreatedAt)
	if err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		n.ApplicationID = &v
	}
	return &n, nil
}

// ListInterviewNotes lists notes, optionally filtered by application ID
// (pass 0 to list all). Most recent first.
func (db *Database) ListInterviewNotes(appID int64) ([]InterviewNote, error) {
	query := `SELECT id, application_id, company, position, round, date, questions, self_reflection, difficulty_points, mood, created_at FROM interview_notes`
	var args []interface{}
	if appID > 0 {
		query += ` WHERE application_id = ?`
		args = append(args, appID)
	}
	query += ` ORDER BY created_at DESC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []InterviewNote
	for rows.Next() {
		var n InterviewNote
		var aid sql.NullInt64
		if err := rows.Scan(&n.ID, &aid, &n.Company, &n.Position, &n.Round, &n.Date, &n.Questions, &n.SelfReflection, &n.DifficultyPoints, &n.Mood, &n.CreatedAt); err != nil {
			return nil, err
		}
		if aid.Valid {
			v := aid.Int64
			n.ApplicationID = &v
		}
		out = append(out, n)
	}
	return out, nil
}

// UpdateInterviewNote updates an existing note.
func (db *Database) UpdateInterviewNote(n *InterviewNote) error {
	_, err := db.conn.Exec(
		`UPDATE interview_notes SET company = ?, position = ?, round = ?, date = ?, questions = ?, self_reflection = ?, difficulty_points = ?, mood = ? WHERE id = ?`,
		n.Company, n.Position, n.Round, n.Date, n.Questions, n.SelfReflection, n.DifficultyPoints, n.Mood, n.ID,
	)
	return err
}

// DeleteInterviewNote removes a note by ID.
func (db *Database) DeleteInterviewNote(id int64) error {
	_, err := db.conn.Exec(`DELETE FROM interview_notes WHERE id = ?`, id)
	return err
}

// ensure sql package is referenced even if all helpers later move out
var _ = sql.ErrNoRows