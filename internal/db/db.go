package db

import (
	"database/sql"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

// Application represents a job application record
type Application struct {
	ID           int64     `json:"id"`
	CompanyName  string    `json:"company_name"`
	PositionName string    `json:"position_name"`
	JobURL       string    `json:"job_url"`
	Status       string    `json:"status"` // applied | assessment | written_test | interview | offer | eliminated | rejected
	Source       string    `json:"source"` // cli | web | import
	Notes        string    `json:"notes"`
	AppliedAt    time.Time `json:"applied_at"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

// Event represents a test/interview/assessment event
type Event struct {
	ID            int64      `json:"id"`
	ApplicationID int64      `json:"application_id"`
	EventType     string     `json:"event_type"` // written_test | interview | assessment | other
	Round         int        `json:"round"`
	ScheduledAt   *time.Time `json:"scheduled_at"`
	Duration      string     `json:"duration"`
	Location      string     `json:"location"`
	Notes         string     `json:"notes"`
	CreatedAt     time.Time  `json:"created_at"`
}

// InterviewNote represents an interview review/retrospective
type InterviewNote struct {
	ID               int64     `json:"id"`
	ApplicationID    *int64    `json:"application_id,omitempty"`
	Company          string    `json:"company"`
	Position         string    `json:"position"`
	Round            string    `json:"round"`
	Date             string    `json:"date"`
	Questions        string    `json:"questions"`
	SelfReflection   string    `json:"self_reflection"`
	DifficultyPoints string    `json:"difficulty_points"`
	Mood             string    `json:"mood"`
	CreatedAt        time.Time `json:"created_at"`
}

// Database wraps the SQL connection
type Database struct {
	conn *sql.DB
}

// Init opens or creates the SQLite database and runs migrations
func Init(dbPath string) (*Database, error) {
	conn, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	conn.SetMaxOpenConns(1) // SQLite single-writer
	if _, err := conn.Exec(`PRAGMA foreign_keys = ON`); err != nil {
		conn.Close()
		return nil, fmt.Errorf("enable foreign keys: %w", err)
	}

	db := &Database{conn: conn}
	if err := db.migrate(); err != nil {
		conn.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return db, nil
}

// Close closes the database connection
func (db *Database) Close() error {
	return db.conn.Close()
}

// migrate creates tables if they don't exist
func (db *Database) migrate() error {
	migrations := []string{
		`CREATE TABLE IF NOT EXISTS applications (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			company_name TEXT NOT NULL,
			position_name TEXT NOT NULL,
			job_url TEXT DEFAULT '',
			status TEXT NOT NULL DEFAULT 'applied',
			source TEXT NOT NULL DEFAULT 'cli',
			notes TEXT DEFAULT '',
			applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS events (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			application_id INTEGER NOT NULL,
			event_type TEXT NOT NULL,
			round INTEGER DEFAULT 0,
			scheduled_at DATETIME,
			duration TEXT DEFAULT '',
			location TEXT DEFAULT '',
			notes TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS interview_notes (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			application_id INTEGER,
			company TEXT NOT NULL,
			position TEXT NOT NULL,
			round TEXT DEFAULT '',
			date TEXT DEFAULT '',
			questions TEXT DEFAULT '',
			self_reflection TEXT DEFAULT '',
			difficulty_points TEXT DEFAULT '',
			mood TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
		)`,
		`CREATE TABLE IF NOT EXISTS resumes (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT DEFAULT '',
			file_path TEXT,
			parsed_data TEXT,
			parse_status TEXT DEFAULT 'pending',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS jd_analyses (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			application_id INTEGER,
			jd_source TEXT NOT NULL DEFAULT 'text',
			jd_text TEXT NOT NULL,
			result TEXT NOT NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
		)`,
		`CREATE TABLE IF NOT EXISTS resume_matches (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			resume_id INTEGER NOT NULL,
			application_id INTEGER,
			jd_text TEXT NOT NULL,
			result TEXT NOT NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
		)`,
		`CREATE TABLE IF NOT EXISTS conversations (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			title TEXT NOT NULL DEFAULT '新对话',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS chat_messages (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			conversation_id INTEGER NOT NULL,
			role TEXT NOT NULL,
			content TEXT DEFAULT '',
			tool_calls TEXT DEFAULT '',
			tool_call_id TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
		)`,
		`CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id)`,
		`CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)`,
		`CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_jd_app ON jd_analyses(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_matches_resume ON resume_matches(resume_id)`,
		`CREATE INDEX IF NOT EXISTS idx_notes_app ON interview_notes(application_id)`,
	}

	for _, m := range migrations {
		if _, err := db.conn.Exec(m); err != nil {
			return fmt.Errorf("migration failed: %w\nSQL: %s", err, m)
		}
	}
	return nil
}

// CreateApplication inserts a new application record
func (db *Database) CreateApplication(app *Application) error {
	res, err := db.conn.Exec(
		`INSERT INTO applications (company_name, position_name, job_url, status, source, notes, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		app.CompanyName, app.PositionName, app.JobURL, app.Status, app.Source, app.Notes, app.AppliedAt,
	)
	if err != nil {
		return err
	}
	app.ID, _ = res.LastInsertId()
	app.CreatedAt = time.Now()
	app.UpdatedAt = time.Now()
	return nil
}

// ListApplications retrieves all applications, optionally filtered by status
func (db *Database) ListApplications(statusFilter string) ([]Application, error) {
	query := `SELECT id, company_name, position_name, job_url, status, source, notes, applied_at, created_at, updated_at FROM applications`
	var args []interface{}
	if statusFilter != "" {
		query += ` WHERE status = ?`
		args = append(args, statusFilter)
	}
	query += ` ORDER BY applied_at DESC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var apps []Application
	for rows.Next() {
		var app Application
		if err := rows.Scan(&app.ID, &app.CompanyName, &app.PositionName, &app.JobURL, &app.Status, &app.Source, &app.Notes, &app.AppliedAt, &app.CreatedAt, &app.UpdatedAt); err != nil {
			return nil, err
		}
		apps = append(apps, app)
	}
	return apps, nil
}

// GetApplication retrieves a single application by ID
func (db *Database) GetApplication(id int64) (*Application, error) {
	var app Application
	err := db.conn.QueryRow(
		`SELECT id, company_name, position_name, job_url, status, source, notes, applied_at, created_at, updated_at FROM applications WHERE id = ?`, id,
	).Scan(&app.ID, &app.CompanyName, &app.PositionName, &app.JobURL, &app.Status, &app.Source, &app.Notes, &app.AppliedAt, &app.CreatedAt, &app.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &app, nil
}

// UpdateApplication updates an application's status and notes
func (db *Database) UpdateApplication(app *Application) error {
	_, err := db.conn.Exec(
		`UPDATE applications SET company_name = ?, position_name = ?, job_url = ?, status = ?, notes = ?, updated_at = ? WHERE id = ?`,
		app.CompanyName, app.PositionName, app.JobURL, app.Status, app.Notes, time.Now(), app.ID,
	)
	return err
}

// DeleteApplication deletes an application by ID
func (db *Database) DeleteApplication(id int64) error {
	_, err := db.conn.Exec(`DELETE FROM applications WHERE id = ?`, id)
	return err
}
