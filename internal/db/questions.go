package db

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"
	"unicode"
)

// Question status values.
const (
	QuestionStatusNew        = "new"
	QuestionStatusPracticing = "practicing"
	QuestionStatusMastered   = "mastered"
)

// Question review ratings (self-assessment during practice check-in).
const (
	QuestionRatingAgain = 1 // 不会 — review again soon
	QuestionRatingHard  = 2 // 模糊 — review in a few days
	QuestionRatingGood  = 3 // 掌握 — mastered
)

const questionCols = `id, knowledge_base_id, application_id, category, difficulty, question, reference_answer, tags, source_type, status, practice_count, last_practiced_at, next_review_at, created_at, updated_at`

// QuestionFilter filters question listings.
type QuestionFilter struct {
	KnowledgeBaseID int64
	Category        string
	Difficulty      string
	Status          string
}

// QuestionPracticeStats summarizes practice progress across the whole bank.
type QuestionPracticeStats struct {
	Total        int `json:"total"`
	New          int `json:"new"`
	Practicing   int `json:"practicing"`
	Mastered     int `json:"mastered"`
	Due          int `json:"due"`
	TodayReviews int `json:"today_reviews"`
	StreakDays   int `json:"streak_days"`
}

// QuestionDigest is a lightweight view of a stored question used for dedup.
type QuestionDigest struct {
	ID       int64  `json:"id"`
	Question string `json:"question"`
	Hash     string `json:"hash"`
}

// NormalizeQuestion produces a canonical form of a question used for exact
// dedup: it lowercases, folds full-width characters to half-width, and drops
// all whitespace and punctuation so trivially different phrasings collapse.
func NormalizeQuestion(text string) string {
	var b strings.Builder
	for _, r := range text {
		// Fold common full-width ASCII range to half-width.
		if r >= 0xFF01 && r <= 0xFF5E {
			r -= 0xFEE0
		}
		if r == 0x3000 { // full-width space
			continue
		}
		if unicode.IsSpace(r) || unicode.IsPunct(r) || unicode.IsSymbol(r) {
			continue
		}
		b.WriteRune(unicode.ToLower(r))
	}
	return b.String()
}

// QuestionHash returns the sha256 hex of the normalized question text.
func QuestionHash(text string) string {
	sum := sha256.Sum256([]byte(NormalizeQuestion(text)))
	return hex.EncodeToString(sum[:])
}

// ListQuestionDigests returns id/question/hash for every stored question so
// callers can dedup newly generated questions against the existing bank.
func (db *Database) ListQuestionDigests() ([]QuestionDigest, error) {
	rows, err := db.conn.Query(`SELECT id, question, question_hash FROM questions`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []QuestionDigest
	for rows.Next() {
		var d QuestionDigest
		if err := rows.Scan(&d.ID, &d.Question, &d.Hash); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// CreateQuestion inserts a single question.
func (db *Database) CreateQuestion(q *Question) error {
	now := time.Now()
	tagsJSON, err := marshalQuestionTags(q.Tags)
	if err != nil {
		return err
	}
	q.Status = defaultQuestionStatus(q.Status)
	q.QuestionHash = QuestionHash(q.Question)
	res, err := db.conn.Exec(
		`INSERT INTO questions (knowledge_base_id, application_id, category, difficulty, question, reference_answer, tags, source_type, status, practice_count, last_practiced_at, next_review_at, question_hash, created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		nullableInt64(q.KnowledgeBaseID), nullableInt64(q.ApplicationID), q.Category, q.Difficulty, q.Question, q.ReferenceAnswer,
		tagsJSON, q.SourceType, q.Status, q.PracticeCount, nullableTime(q.LastPracticedAt), nullableTime(q.NextReviewAt), q.QuestionHash, now, now,
	)
	if err != nil {
		return err
	}
	q.ID, _ = res.LastInsertId()
	q.CreatedAt = now
	q.UpdatedAt = now
	return nil
}

// BulkCreateQuestions inserts many questions in a single transaction.
// Each question's ID is populated on success.
func (db *Database) BulkCreateQuestions(questions []*Question) error {
	if len(questions) == 0 {
		return nil
	}
	tx, err := db.conn.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	stmt, err := tx.Prepare(
		`INSERT INTO questions (knowledge_base_id, application_id, category, difficulty, question, reference_answer, tags, source_type, status, practice_count, last_practiced_at, next_review_at, question_hash, created_at, updated_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
	)
	if err != nil {
		return err
	}
	defer stmt.Close()

	now := time.Now()
	for _, q := range questions {
		tagsJSON, err := marshalQuestionTags(q.Tags)
		if err != nil {
			return err
		}
		q.Status = defaultQuestionStatus(q.Status)
		q.QuestionHash = QuestionHash(q.Question)
		res, err := stmt.Exec(
			nullableInt64(q.KnowledgeBaseID), nullableInt64(q.ApplicationID), q.Category, q.Difficulty, q.Question, q.ReferenceAnswer,
			tagsJSON, q.SourceType, q.Status, q.PracticeCount, nullableTime(q.LastPracticedAt), nullableTime(q.NextReviewAt), q.QuestionHash, now, now,
		)
		if err != nil {
			return err
		}
		q.ID, _ = res.LastInsertId()
		q.CreatedAt = now
		q.UpdatedAt = now
	}
	return tx.Commit()
}

// ListQuestions lists questions matching the filter, most recent first.
func (db *Database) ListQuestions(filter QuestionFilter) ([]Question, error) {
	query := `SELECT ` + questionCols + ` FROM questions`
	var args []interface{}
	var where []string
	if filter.KnowledgeBaseID > 0 {
		where = append(where, "knowledge_base_id = ?")
		args = append(args, filter.KnowledgeBaseID)
	}
	if filter.Category != "" {
		where = append(where, "category = ?")
		args = append(args, filter.Category)
	}
	if filter.Difficulty != "" {
		where = append(where, "difficulty = ?")
		args = append(args, filter.Difficulty)
	}
	if filter.Status != "" {
		where = append(where, "status = ?")
		args = append(args, filter.Status)
	}
	for i, clause := range where {
		if i == 0 {
			query += " WHERE "
		} else {
			query += " AND "
		}
		query += clause
	}
	query += ` ORDER BY created_at DESC, id DESC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Question
	for rows.Next() {
		q, err := scanQuestion(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *q)
	}
	return out, rows.Err()
}

// ListDueQuestions returns questions that are due for review (next_review_at
// in the past) plus never-practiced questions, oldest-due first, capped by limit.
func (db *Database) ListDueQuestions(limit int) ([]Question, error) {
	if limit <= 0 {
		limit = 20
	}
	rows, err := db.conn.Query(
		`SELECT `+questionCols+` FROM questions
			WHERE next_review_at IS NULL OR next_review_at <= ?
			ORDER BY next_review_at IS NOT NULL, next_review_at ASC, created_at ASC
			LIMIT ?`,
		time.Now(), limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var out []Question
	for rows.Next() {
		q, err := scanQuestion(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *q)
	}
	return out, rows.Err()
}

// GetQuestion retrieves a single question by ID.
func (db *Database) GetQuestion(id int64) (*Question, error) {
	row := db.conn.QueryRow(`SELECT `+questionCols+` FROM questions WHERE id = ?`, id)
	return scanQuestion(row)
}

// UpdateQuestion updates the editable fields of a question.
func (db *Database) UpdateQuestion(q *Question) error {
	tagsJSON, err := marshalQuestionTags(q.Tags)
	if err != nil {
		return err
	}
	res, err := db.conn.Exec(
		`UPDATE questions SET category = ?, difficulty = ?, question = ?, reference_answer = ?, tags = ?, status = ?, updated_at = ? WHERE id = ?`,
		q.Category, q.Difficulty, q.Question, q.ReferenceAnswer, tagsJSON, defaultQuestionStatus(q.Status), time.Now(), q.ID,
	)
	if err != nil {
		return err
	}
	return errNoRowsWhenUnchanged(res)
}

// DeleteQuestion removes a question (and cascades its reviews) by ID.
func (db *Database) DeleteQuestion(id int64) error {
	res, err := db.conn.Exec(`DELETE FROM questions WHERE id = ?`, id)
	if err != nil {
		return err
	}
	return errNoRowsWhenUnchanged(res)
}

// AddQuestionReview records a practice check-in and updates the question's
// derived state (practice_count, status, last/next review timestamps) in one
// transaction. It returns the updated question.
func (db *Database) AddQuestionReview(review *QuestionReview) (*Question, error) {
	tx, err := db.conn.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	now := time.Now()
	res, err := tx.Exec(
		`INSERT INTO question_reviews (question_id, rating, note, created_at) VALUES (?, ?, ?, ?)`,
		review.QuestionID, review.Rating, review.Note, now,
	)
	if err != nil {
		return nil, err
	}
	review.ID, _ = res.LastInsertId()
	review.CreatedAt = now

	status := QuestionStatusPracticing
	if review.Rating >= QuestionRatingGood {
		status = QuestionStatusMastered
	}
	next := now.Add(nextReviewInterval(review.Rating))

	upd, err := tx.Exec(
		`UPDATE questions SET practice_count = practice_count + 1, status = ?, last_practiced_at = ?, next_review_at = ?, updated_at = ? WHERE id = ?`,
		status, now, next, now, review.QuestionID,
	)
	if err != nil {
		return nil, err
	}
	if err := errNoRowsWhenUnchanged(upd); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return db.GetQuestion(review.QuestionID)
}

// PracticeStats computes progress metrics across the whole question bank.
func (db *Database) PracticeStats() (*QuestionPracticeStats, error) {
	stats := &QuestionPracticeStats{}
	now := time.Now()

	err := db.conn.QueryRow(
		`SELECT
			COUNT(*),
			COALESCE(SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END), 0),
			COALESCE(SUM(CASE WHEN status = 'practicing' THEN 1 ELSE 0 END), 0),
			COALESCE(SUM(CASE WHEN status = 'mastered' THEN 1 ELSE 0 END), 0),
			COALESCE(SUM(CASE WHEN next_review_at IS NULL OR next_review_at <= ? THEN 1 ELSE 0 END), 0)
		FROM questions`, now,
	).Scan(&stats.Total, &stats.New, &stats.Practicing, &stats.Mastered, &stats.Due)
	if err != nil {
		return nil, err
	}

	startOfDay := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	if err := db.conn.QueryRow(
		`SELECT COUNT(*) FROM question_reviews WHERE created_at >= ?`, startOfDay,
	).Scan(&stats.TodayReviews); err != nil {
		return nil, err
	}

	streak, err := db.reviewStreakDays(now)
	if err != nil {
		return nil, err
	}
	stats.StreakDays = streak
	return stats, nil
}

// reviewStreakDays counts consecutive days (ending today or yesterday) that
// have at least one practice check-in. Dates are derived in Go to stay
// independent of how the driver serializes timestamps.
func (db *Database) reviewStreakDays(now time.Time) (int, error) {
	rows, err := db.conn.Query(`SELECT created_at FROM question_reviews ORDER BY created_at DESC`)
	if err != nil {
		return 0, err
	}
	defer rows.Close()

	seen := make(map[string]bool)
	var days []string // unique local dates, most recent first
	for rows.Next() {
		var ts time.Time
		if err := rows.Scan(&ts); err != nil {
			return 0, err
		}
		day := ts.In(now.Location()).Format("2006-01-02")
		if !seen[day] {
			seen[day] = true
			days = append(days, day)
		}
	}
	if err := rows.Err(); err != nil {
		return 0, err
	}
	if len(days) == 0 {
		return 0, nil
	}

	today := now.Format("2006-01-02")
	yesterday := now.AddDate(0, 0, -1).Format("2006-01-02")
	// Streak stays alive only if the latest check-in was today or yesterday.
	if days[0] != today && days[0] != yesterday {
		return 0, nil
	}

	streak := 0
	expected := days[0]
	for _, day := range days {
		if day != expected {
			break
		}
		streak++
		d, err := time.ParseInLocation("2006-01-02", expected, now.Location())
		if err != nil {
			return 0, err
		}
		expected = d.AddDate(0, 0, -1).Format("2006-01-02")
	}
	return streak, nil
}

// nextReviewInterval maps a self-assessment rating to a review interval.
func nextReviewInterval(rating int) time.Duration {
	switch {
	case rating <= QuestionRatingAgain:
		return 24 * time.Hour
	case rating == QuestionRatingHard:
		return 3 * 24 * time.Hour
	default:
		return 7 * 24 * time.Hour
	}
}

func defaultQuestionStatus(status string) string {
	if status == "" {
		return QuestionStatusNew
	}
	return status
}

func marshalQuestionTags(tags []string) (string, error) {
	if tags == nil {
		return "[]", nil
	}
	b, err := json.Marshal(tags)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

type questionScanner interface {
	Scan(dest ...interface{}) error
}

func scanQuestion(scanner questionScanner) (*Question, error) {
	var q Question
	var kbID, appID sql.NullInt64
	var tagsJSON string
	var lastPracticed, nextReview sql.NullTime
	if err := scanner.Scan(
		&q.ID, &kbID, &appID, &q.Category, &q.Difficulty, &q.Question, &q.ReferenceAnswer,
		&tagsJSON, &q.SourceType, &q.Status, &q.PracticeCount, &lastPracticed, &nextReview, &q.CreatedAt, &q.UpdatedAt,
	); err != nil {
		return nil, err
	}
	if kbID.Valid {
		v := kbID.Int64
		q.KnowledgeBaseID = &v
	}
	if appID.Valid {
		v := appID.Int64
		q.ApplicationID = &v
	}
	if tagsJSON != "" {
		if err := json.Unmarshal([]byte(tagsJSON), &q.Tags); err != nil {
			return nil, err
		}
	}
	q.LastPracticedAt = timePtrFromNull(lastPracticed)
	q.NextReviewAt = timePtrFromNull(nextReview)
	return &q, nil
}
