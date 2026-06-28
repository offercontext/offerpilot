package db

import (
	"database/sql"
	"time"
)

// Resume stores a resume as plain text (MVP). parsed_data holds the text,
// parse_status is "text-ready" once text is loaded. file_path is set only when
// the resume came from a local file.
type Resume struct {
	ID           int64     `json:"id"`
	Name         string    `json:"name"`
	FilePath     string    `json:"file_path"`
	ParsedData   string    `json:"parsed_data"` // resume text
	ParseStatus  string    `json:"parse_status"`
	CreatedAt    time.Time `json:"created_at"`
}

// ResumeMatch stores the result of matching a resume against a JD.
type ResumeMatch struct {
	ID            int64     `json:"id"`
	ResumeID      int64     `json:"resume_id"`
	ApplicationID *int64    `json:"application_id,omitempty"`
	JDText        string    `json:"jd_text"`
	Result        string    `json:"result"` // JSON string
	CreatedAt     time.Time `json:"created_at"`
}

// CreateResume inserts a resume record.
func (db *Database) CreateResume(r *Resume) error {
	if r.ParseStatus == "" {
		r.ParseStatus = "text-ready"
	}
	res, err := db.conn.Exec(
		`INSERT INTO resumes (name, file_path, parsed_data, parse_status) VALUES (?, ?, ?, ?)`,
		r.Name, r.FilePath, r.ParsedData, r.ParseStatus,
	)
	if err != nil {
		return err
	}
	r.ID, _ = res.LastInsertId()
	r.CreatedAt = time.Now()
	return nil
}

// GetResume retrieves a single resume by ID.
func (db *Database) GetResume(id int64) (*Resume, error) {
	var r Resume
	err := db.conn.QueryRow(
		`SELECT id, name, file_path, parsed_data, parse_status, created_at FROM resumes WHERE id = ?`, id,
	).Scan(&r.ID, &r.Name, &r.FilePath, &r.ParsedData, &r.ParseStatus, &r.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// ListResumes returns all resumes, most recent first.
func (db *Database) ListResumes() ([]Resume, error) {
	rows, err := db.conn.Query(
		`SELECT id, name, file_path, parsed_data, parse_status, created_at FROM resumes ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Resume
	for rows.Next() {
		var r Resume
		if err := rows.Scan(&r.ID, &r.Name, &r.FilePath, &r.ParsedData, &r.ParseStatus, &r.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

// DeleteResume removes a resume by ID.
func (db *Database) DeleteResume(id int64) error {
	_, err := db.conn.Exec(`DELETE FROM resumes WHERE id = ?`, id)
	return err
}

// CreateResumeMatch inserts a resume-match result.
func (db *Database) CreateResumeMatch(m *ResumeMatch) error {
	res, err := db.conn.Exec(
		`INSERT INTO resume_matches (resume_id, application_id, jd_text, result) VALUES (?, ?, ?, ?)`,
		m.ResumeID, nullableInt64(m.ApplicationID), m.JDText, m.Result,
	)
	if err != nil {
		return err
	}
	m.ID, _ = res.LastInsertId()
	m.CreatedAt = time.Now()
	return nil
}

// GetResumeMatch retrieves a single resume match by ID.
func (db *Database) GetResumeMatch(id int64) (*ResumeMatch, error) {
	var m ResumeMatch
	var appID sql.NullInt64
	err := db.conn.QueryRow(
		`SELECT id, resume_id, application_id, jd_text, result, created_at FROM resume_matches WHERE id = ?`, id,
	).Scan(&m.ID, &m.ResumeID, &appID, &m.JDText, &m.Result, &m.CreatedAt)
	if err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		m.ApplicationID = &v
	}
	return &m, nil
}

// ListResumeMatches lists match results for a resume, most recent first.
func (db *Database) ListResumeMatches(resumeID int64) ([]ResumeMatch, error) {
	rows, err := db.conn.Query(
		`SELECT id, resume_id, application_id, jd_text, result, created_at FROM resume_matches WHERE resume_id = ? ORDER BY created_at DESC`,
		resumeID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []ResumeMatch
	for rows.Next() {
		var m ResumeMatch
		var aid sql.NullInt64
		if err := rows.Scan(&m.ID, &m.ResumeID, &aid, &m.JDText, &m.Result, &m.CreatedAt); err != nil {
			return nil, err
		}
		if aid.Valid {
			v := aid.Int64
			m.ApplicationID = &v
		}
		out = append(out, m)
	}
	return out, nil
}