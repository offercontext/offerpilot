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

// Offer represents a compensation offer, optionally linked to an application.
type Offer struct {
	ID            int64     `json:"id"`
	ApplicationID *int64    `json:"application_id,omitempty"`
	CompanyName   string    `json:"company_name"`
	PositionName  string    `json:"position_name"`
	Status        string    `json:"status"` // pending|negotiating|accepted|declined|expired
	BaseMonthly   int64     `json:"base_monthly"`
	MonthsPerYear int64     `json:"months_per_year"`
	SigningBonus  int64     `json:"signing_bonus"`
	Equity        string    `json:"equity"`
	Perks         string    `json:"perks"`
	Deadline      string    `json:"deadline"`
	Notes         string    `json:"notes"`
	Assessment    string    `json:"assessment"`
	TotalCash     int64     `json:"total_cash"` // derived: base*months+signing, not stored
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

// Question represents an interview practice question, usually AI-generated
// from a knowledge base or interview retrospectives.
type Question struct {
	ID              int64      `json:"id"`
	KnowledgeBaseID *int64     `json:"knowledge_base_id,omitempty"`
	ApplicationID   *int64     `json:"application_id,omitempty"`
	Category        string     `json:"category"`
	Difficulty      string     `json:"difficulty"` // easy | medium | hard
	Question        string     `json:"question"`
	ReferenceAnswer string     `json:"reference_answer"`
	Tags            []string   `json:"tags"`
	SourceType      string     `json:"source_type"` // ai_knowledge | ai_notes | manual
	Status          string     `json:"status"`      // new | practicing | mastered
	PracticeCount   int        `json:"practice_count"`
	LastPracticedAt *time.Time `json:"last_practiced_at,omitempty"`
	NextReviewAt    *time.Time `json:"next_review_at,omitempty"`
	QuestionHash    string     `json:"-"` // sha256 of normalized question text, for dedup
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
}

// MockSession is an AI mock-interview practice session. The live dialogue is
// stored in the bound Conversation (mode='mock_interview'); this table holds
// the immutable session config, progress and final AI scoring/feedback.
type MockSession struct {
	ID                 int64      `json:"id"`
	ConversationID     int64      `json:"conversation_id"`
	ApplicationID      *int64     `json:"application_id,omitempty"`
	Title              string     `json:"title"`
	Role               string     `json:"role"`                 // target role, e.g. "后端开发"
	Company            string     `json:"company"`              // optional target company
	RoundType          string     `json:"round_type"`           // technical | behavioral | coding | hr | mixed
	Difficulty         string     `json:"difficulty"`           // easy | medium | hard
	QuestionCount      int        `json:"question_count"`        // 0 = unlimited
	DurationMin        int        `json:"duration_min"`          // 0 = unlimited
	QuestionSource     string     `json:"question_source"`      // bank | knowledge | notes | mixed
	KnowledgeBaseID    *int64     `json:"knowledge_base_id,omitempty"`
	Status             string     `json:"status"`               // in_progress | completed | aborted
	QuestionIndex      int        `json:"question_index"`
	StartedAt          time.Time  `json:"started_at"`
	EndedAt            *time.Time `json:"ended_at,omitempty"`
	ScoreOverall       *int       `json:"score_overall,omitempty"`
	ScoreCommunication *int       `json:"score_communication,omitempty"`
	ScoreDepth         *int       `json:"score_depth,omitempty"`
	ScoreStructure     *int       `json:"score_structure,omitempty"`
	ScoreConfidence    *int       `json:"score_confidence,omitempty"`
	Feedback           string     `json:"feedback,omitempty"`   // JSON string
	CreatedAt          time.Time  `json:"created_at"`
}

// QuestionReview is a single practice check-in for a question.
type QuestionReview struct {
	ID         int64     `json:"id"`
	QuestionID int64     `json:"question_id"`
	Rating     int       `json:"rating"` // 1 = again | 2 = hard | 3 = good
	Note       string    `json:"note"`
	CreatedAt  time.Time `json:"created_at"`
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
		`CREATE TABLE IF NOT EXISTS offers (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			application_id INTEGER,
			company_name TEXT NOT NULL,
			position_name TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'pending',
			base_monthly INTEGER NOT NULL DEFAULT 0,
			months_per_year INTEGER NOT NULL DEFAULT 12,
			signing_bonus INTEGER NOT NULL DEFAULT 0,
			equity TEXT DEFAULT '',
			perks TEXT DEFAULT '',
			deadline TEXT DEFAULT '',
			notes TEXT DEFAULT '',
			assessment TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
			provider_blocks TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS knowledge_bases (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			description TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,
		`CREATE TABLE IF NOT EXISTS knowledge_documents (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			knowledge_base_id INTEGER NOT NULL,
			title TEXT NOT NULL,
			content TEXT NOT NULL DEFAULT '',
			tags TEXT NOT NULL DEFAULT '[]',
			source_type TEXT NOT NULL DEFAULT 'manual',
			source_name TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS knowledge_chunks (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			document_id INTEGER NOT NULL,
			knowledge_base_id INTEGER NOT NULL,
			chunk_index INTEGER NOT NULL DEFAULT 0,
			content TEXT NOT NULL,
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
			FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
		)`,
		`CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
			chunk_id UNINDEXED,
			document_id UNINDEXED,
			knowledge_base_id UNINDEXED,
			content
		)`,
		`CREATE TABLE IF NOT EXISTS questions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			knowledge_base_id INTEGER,
			application_id INTEGER,
			category TEXT DEFAULT '',
			difficulty TEXT NOT NULL DEFAULT 'medium',
			question TEXT NOT NULL,
			reference_answer TEXT DEFAULT '',
			tags TEXT NOT NULL DEFAULT '[]',
			source_type TEXT NOT NULL DEFAULT 'ai_knowledge',
			status TEXT NOT NULL DEFAULT 'new',
			practice_count INTEGER NOT NULL DEFAULT 0,
			last_practiced_at DATETIME,
			next_review_at DATETIME,
			question_hash TEXT NOT NULL DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE SET NULL,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
		)`,
		`CREATE TABLE IF NOT EXISTS question_reviews (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			question_id INTEGER NOT NULL,
			rating INTEGER NOT NULL DEFAULT 0,
			note TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS application_material_kits (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			application_id INTEGER NOT NULL UNIQUE,
			resume_id INTEGER,
			jd_analysis_id INTEGER,
			jd_snapshot TEXT DEFAULT '',
			status TEXT NOT NULL DEFAULT 'draft',
			content_json TEXT NOT NULL DEFAULT '{}',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
			FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE SET NULL,
			FOREIGN KEY (jd_analysis_id) REFERENCES jd_analyses(id) ON DELETE SET NULL
		)`,
		`CREATE INDEX IF NOT EXISTS idx_material_kits_app ON application_material_kits(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_material_kits_status ON application_material_kits(status)`,
		`CREATE INDEX IF NOT EXISTS idx_chat_messages_conv ON chat_messages(conversation_id)`,
		`CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)`,
		`CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_jd_app ON jd_analyses(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_matches_resume ON resume_matches(resume_id)`,
		`CREATE INDEX IF NOT EXISTS idx_notes_app ON interview_notes(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_knowledge_documents_base ON knowledge_documents(knowledge_base_id)`,
		`CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id)`,
		`CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_base ON knowledge_chunks(knowledge_base_id)`,
		`CREATE INDEX IF NOT EXISTS idx_offers_app ON offers(application_id)`,
		`CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status)`,
		`CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status)`,
		`CREATE INDEX IF NOT EXISTS idx_questions_kb ON questions(knowledge_base_id)`,
		`CREATE INDEX IF NOT EXISTS idx_questions_next_review ON questions(next_review_at)`,
		`CREATE INDEX IF NOT EXISTS idx_questions_hash ON questions(question_hash)`,
		`CREATE INDEX IF NOT EXISTS idx_question_reviews_question ON question_reviews(question_id)`,
		`CREATE TABLE IF NOT EXISTS mock_sessions (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			conversation_id INTEGER NOT NULL,
			application_id INTEGER,
			title TEXT NOT NULL DEFAULT '模拟面试',
			role TEXT NOT NULL DEFAULT '',
			company TEXT NOT NULL DEFAULT '',
			round_type TEXT NOT NULL DEFAULT 'technical',
			difficulty TEXT NOT NULL DEFAULT 'medium',
			question_count INTEGER NOT NULL DEFAULT 5,
			duration_min INTEGER NOT NULL DEFAULT 30,
			question_source TEXT NOT NULL DEFAULT 'mixed',
			knowledge_base_id INTEGER,
			status TEXT NOT NULL DEFAULT 'in_progress',
			question_index INTEGER NOT NULL DEFAULT 0,
			started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			ended_at DATETIME,
			score_overall INTEGER,
			score_communication INTEGER,
			score_depth INTEGER,
			score_structure INTEGER,
			score_confidence INTEGER,
			feedback TEXT DEFAULT '',
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
			FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL,
			FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE SET NULL
		)`,
		`CREATE INDEX IF NOT EXISTS idx_mock_sessions_conv ON mock_sessions(conversation_id)`,
		`CREATE INDEX IF NOT EXISTS idx_mock_sessions_status ON mock_sessions(status)`,
	}

	for _, m := range migrations {
		if _, err := db.conn.Exec(m); err != nil {
			return fmt.Errorf("migration failed: %w\nSQL: %s", err, m)
		}
	}
	if err := db.ensureColumn("chat_messages", "provider_blocks", "TEXT DEFAULT ''"); err != nil {
		return err
	}
	if err := db.ensureColumn("conversations", "offer_id", "INTEGER"); err != nil {
		return err
	}
	if err := db.ensureColumn("conversations", "mode", "TEXT DEFAULT 'general'"); err != nil {
		return err
	}
	// Resumes table evolved across versions; ensure columns exist for older DBs
	// whose CREATE TABLE IF NOT EXISTS no-op'd on the current schema.
	if err := db.ensureColumn("resumes", "name", "TEXT DEFAULT ''"); err != nil {
		return err
	}
	if err := db.ensureColumn("resumes", "file_path", "TEXT"); err != nil {
		return err
	}
	if err := db.ensureColumn("resumes", "parsed_data", "TEXT"); err != nil {
		return err
	}
	if err := db.ensureColumn("resumes", "parse_status", "TEXT DEFAULT 'pending'"); err != nil {
		return err
	}
	return nil
}

func (db *Database) ensureColumn(table, column, definition string) error {
	rows, err := db.conn.Query(`PRAGMA table_info(` + table + `)`)
	if err != nil {
		return fmt.Errorf("inspect %s columns: %w", table, err)
	}
	defer rows.Close()
	for rows.Next() {
		var cid int
		var name, typ string
		var notNull int
		var defaultValue interface{}
		var pk int
		if err := rows.Scan(&cid, &name, &typ, &notNull, &defaultValue, &pk); err != nil {
			return fmt.Errorf("scan %s columns: %w", table, err)
		}
		if name == column {
			return nil
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("iterate %s columns: %w", table, err)
	}
	if _, err := db.conn.Exec(`ALTER TABLE ` + table + ` ADD COLUMN ` + column + ` ` + definition); err != nil {
		return fmt.Errorf("add %s.%s column: %w", table, column, err)
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
