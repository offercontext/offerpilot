package db

import (
	"database/sql"
	"fmt"
	"time"
)

// CreateMockSession inserts a new mock-interview session bound to an existing
// conversation (mode='mock_interview'). The caller is responsible for creating
// the conversation first; this layer only persists the session row so the
// chat-table concerns stay in chat.go.
func (db *Database) CreateMockSession(s *MockSession) error {
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO mock_sessions (
			conversation_id, application_id, title, role, company, round_type,
			difficulty, question_count, duration_min, question_source, knowledge_base_id,
			status, question_index, started_at, created_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		s.ConversationID, nullableInt64(s.ApplicationID), s.Title, s.Role, s.Company, s.RoundType,
		s.Difficulty, s.QuestionCount, s.DurationMin, s.QuestionSource, nullableInt64(s.KnowledgeBaseID),
		statusOrDefault(s.Status, "in_progress"), s.QuestionIndex, now, now,
	)
	if err != nil {
		return fmt.Errorf("create mock session: %w", err)
	}
	s.ID, _ = res.LastInsertId()
	s.Status = statusOrDefault(s.Status, "in_progress")
	s.StartedAt = now
	s.CreatedAt = now
	return nil
}

// GetMockSession retrieves a single session by ID.
func (db *Database) GetMockSession(id int64) (*MockSession, error) {
	var s MockSession
	var appID, kbID sql.NullInt64
	var endedAt sql.NullTime
	var so, sc, sd, ss, sf sql.NullInt64
	err := db.conn.QueryRow(
		`SELECT id, conversation_id, application_id, title, role, company, round_type,
			difficulty, question_count, duration_min, question_source, knowledge_base_id,
			status, question_index, started_at, ended_at,
			score_overall, score_communication, score_depth, score_structure, score_confidence,
			feedback, created_at
		FROM mock_sessions WHERE id = ?`, id,
	).Scan(&s.ID, &s.ConversationID, &appID, &s.Title, &s.Role, &s.Company, &s.RoundType,
		&s.Difficulty, &s.QuestionCount, &s.DurationMin, &s.QuestionSource, &kbID,
		&s.Status, &s.QuestionIndex, &s.StartedAt, &endedAt,
		&so, &sc, &sd, &ss, &sf, &s.Feedback, &s.CreatedAt)
	if err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		s.ApplicationID = &v
	}
	if kbID.Valid {
		v := kbID.Int64
		s.KnowledgeBaseID = &v
	}
	if endedAt.Valid {
		t := endedAt.Time
		s.EndedAt = &t
	}
	assignScore(&s.ScoreOverall, so)
	assignScore(&s.ScoreCommunication, sc)
	assignScore(&s.ScoreDepth, sd)
	assignScore(&s.ScoreStructure, ss)
	assignScore(&s.ScoreConfidence, sf)
	return &s, nil
}

// GetMockSessionByConversation looks up the session bound to a conversation id.
func (db *Database) GetMockSessionByConversation(convID int64) (*MockSession, error) {
	var s MockSession
	var appID, kbID sql.NullInt64
	var endedAt sql.NullTime
	var so, sc, sd, ss, sf sql.NullInt64
	err := db.conn.QueryRow(
		`SELECT id, conversation_id, application_id, title, role, company, round_type,
			difficulty, question_count, duration_min, question_source, knowledge_base_id,
			status, question_index, started_at, ended_at,
			score_overall, score_communication, score_depth, score_structure, score_confidence,
			feedback, created_at
		FROM mock_sessions WHERE conversation_id = ?`, convID,
	).Scan(&s.ID, &s.ConversationID, &appID, &s.Title, &s.Role, &s.Company, &s.RoundType,
		&s.Difficulty, &s.QuestionCount, &s.DurationMin, &s.QuestionSource, &kbID,
		&s.Status, &s.QuestionIndex, &s.StartedAt, &endedAt,
		&so, &sc, &sd, &ss, &sf, &s.Feedback, &s.CreatedAt)
	if err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		s.ApplicationID = &v
	}
	if kbID.Valid {
		v := kbID.Int64
		s.KnowledgeBaseID = &v
	}
	if endedAt.Valid {
		t := endedAt.Time
		s.EndedAt = &t
	}
	assignScore(&s.ScoreOverall, so)
	assignScore(&s.ScoreCommunication, sc)
	assignScore(&s.ScoreDepth, sd)
	assignScore(&s.ScoreStructure, ss)
	assignScore(&s.ScoreConfidence, sf)
	return &s, nil
}

// ListMockSessions returns sessions, most recently started first. Pass an empty
// status to list all.
func (db *Database) ListMockSessions(statusFilter string) ([]MockSession, error) {
	query := `SELECT id, conversation_id, application_id, title, role, company, round_type,
		difficulty, question_count, duration_min, question_source, knowledge_base_id,
		status, question_index, started_at, ended_at,
		score_overall, score_communication, score_depth, score_structure, score_confidence,
		feedback, created_at FROM mock_sessions`
	var args []interface{}
	if statusFilter != "" {
		query += ` WHERE status = ?`
		args = append(args, statusFilter)
	}
	query += ` ORDER BY started_at DESC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []MockSession
	for rows.Next() {
		var s MockSession
		var appID, kbID sql.NullInt64
		var endedAt sql.NullTime
		var so, sc, sd, ss, sf sql.NullInt64
		if err := rows.Scan(&s.ID, &s.ConversationID, &appID, &s.Title, &s.Role, &s.Company, &s.RoundType,
			&s.Difficulty, &s.QuestionCount, &s.DurationMin, &s.QuestionSource, &kbID,
			&s.Status, &s.QuestionIndex, &s.StartedAt, &endedAt,
			&so, &sc, &sd, &ss, &sf, &s.Feedback, &s.CreatedAt); err != nil {
			return nil, err
		}
		if appID.Valid {
			v := appID.Int64
			s.ApplicationID = &v
		}
		if kbID.Valid {
			v := kbID.Int64
			s.KnowledgeBaseID = &v
		}
		if endedAt.Valid {
			t := endedAt.Time
			s.EndedAt = &t
		}
		assignScore(&s.ScoreOverall, so)
		assignScore(&s.ScoreCommunication, sc)
		assignScore(&s.ScoreDepth, sd)
		assignScore(&s.ScoreStructure, ss)
		assignScore(&s.ScoreConfidence, sf)
		out = append(out, s)
	}
	return out, rows.Err()
}

// UpdateMockSessionProgress advances the question index of an in-progress session.
func (db *Database) UpdateMockSessionProgress(id int64, questionIndex int) error {
	_, err := db.conn.Exec(
		`UPDATE mock_sessions SET question_index = ? WHERE id = ?`, questionIndex, id,
	)
	return err
}

// MockScores holds the five-dimensional AI scores written at session end.
type MockScores struct {
	ScoreOverall       int
	ScoreCommunication int
	ScoreDepth         int
	ScoreStructure     int
	ScoreConfidence    int
}

// FinishMockSession marks a session completed and persists the AI scores + feedback JSON.
func (db *Database) FinishMockSession(id int64, scores MockScores, feedback string) error {
	now := time.Now()
	_, err := db.conn.Exec(
		`UPDATE mock_sessions SET status = 'completed', ended_at = ?,
			score_overall = ?, score_communication = ?, score_depth = ?,
			score_structure = ?, score_confidence = ?, feedback = ? WHERE id = ?`,
		now, scores.ScoreOverall, scores.ScoreCommunication, scores.ScoreDepth,
		scores.ScoreStructure, scores.ScoreConfidence, feedback, id,
	)
	return err
}

// AbortMockSession marks a session aborted without scoring.
func (db *Database) AbortMockSession(id int64) error {
	now := time.Now()
	_, err := db.conn.Exec(
		`UPDATE mock_sessions SET status = 'aborted', ended_at = ? WHERE id = ?`, now, id,
	)
	return err
}

// DeleteMockSession removes a session row. The bound conversation + its messages
// are removed separately (cascade on chat_messages) by the caller.
func (db *Database) DeleteMockSession(id int64) error {
	_, err := db.conn.Exec(`DELETE FROM mock_sessions WHERE id = ?`, id)
	return err
}

// statusOrDefault returns s when non-empty, else def.
func statusOrDefault(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

// assignScore copies a nullable score column into the *int field.
func assignScore(dst **int, src sql.NullInt64) {
	if src.Valid {
		v := int(src.Int64)
		*dst = &v
	}
}