package db

import (
	"database/sql"
	"time"
)

// JDAnalysis stores a JD text plus the AI-generated analysis JSON.
// Result is the raw JSON string from the model (kept verbatim so the API can
// forward it without re-marshalling).
type JDAnalysis struct {
	ID            int64      `json:"id"`
	ApplicationID *int64     `json:"application_id,omitempty"`
	JDSource      string     `json:"jd_source"` // text | url
	JDText        string     `json:"jd_text"`
	Result        string     `json:"result"` // JSON string
	CreatedAt     time.Time  `json:"created_at"`
}

// CreateJDAnalysis inserts a JD analysis record.
func (db *Database) CreateJDAnalysis(a *JDAnalysis) error {
	res, err := db.conn.Exec(
		`INSERT INTO jd_analyses (application_id, jd_source, jd_text, result) VALUES (?, ?, ?, ?)`,
		nullableInt64(a.ApplicationID), a.JDSource, a.JDText, a.Result,
	)
	if err != nil {
		return err
	}
	a.ID, _ = res.LastInsertId()
	a.CreatedAt = time.Now()
	return nil
}

// GetJDAnalysis retrieves a single JD analysis by ID.
func (db *Database) GetJDAnalysis(id int64) (*JDAnalysis, error) {
	var a JDAnalysis
	var appID sql.NullInt64
	err := db.conn.QueryRow(
		`SELECT id, application_id, jd_source, jd_text, result, created_at FROM jd_analyses WHERE id = ?`, id,
	).Scan(&a.ID, &appID, &a.JDSource, &a.JDText, &a.Result, &a.CreatedAt)
	if err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		a.ApplicationID = &v
	}
	return &a, nil
}

// ListJDAnalyses lists JD analyses, optionally filtered by application ID.
// When appID is 0, all analyses are returned (most recent first).
func (db *Database) ListJDAnalyses(appID int64) ([]JDAnalysis, error) {
	query := `SELECT id, application_id, jd_source, jd_text, result, created_at FROM jd_analyses`
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

	var out []JDAnalysis
	for rows.Next() {
		var a JDAnalysis
		var aid sql.NullInt64
		if err := rows.Scan(&a.ID, &aid, &a.JDSource, &a.JDText, &a.Result, &a.CreatedAt); err != nil {
			return nil, err
		}
		if aid.Valid {
			v := aid.Int64
			a.ApplicationID = &v
		}
		out = append(out, a)
	}
	return out, nil
}

// nullableInt64 converts *int64 to interface{} suitable for sql driver.
func nullableInt64(v *int64) interface{} {
	if v == nil {
		return nil
	}
	return *v
}