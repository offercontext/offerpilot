package db

import (
	"database/sql"
	"testing"
	"time"
)

func TestInitUpgradesLegacyQuestionPracticeSchema(t *testing.T) {
	path := t.TempDir() + "/legacy-questions.db"
	conn, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open legacy db: %v", err)
	}
	_, err = conn.Exec(`
		CREATE TABLE questions (
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
			created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
		);
		INSERT INTO questions (question, created_at, updated_at) VALUES ('legacy question', ?, ?);
	`, time.Now(), time.Now())
	if closeErr := conn.Close(); closeErr != nil {
		t.Fatalf("close legacy db: %v", closeErr)
	}
	if err != nil {
		t.Fatalf("seed legacy db: %v", err)
	}

	d, err := Init(path)
	if err != nil {
		t.Fatalf("init legacy db: %v", err)
	}
	defer d.Close()

	if err := d.CreateQuestion(&Question{Question: "new question", Difficulty: "easy"}); err != nil {
		t.Fatalf("create question after migration: %v", err)
	}
	digests, err := d.ListQuestionDigests()
	if err != nil {
		t.Fatalf("list digests after migration: %v", err)
	}
	if len(digests) != 2 {
		t.Fatalf("expected legacy and new question digests, got %d", len(digests))
	}
	due, err := d.ListDueQuestions(10)
	if err != nil {
		t.Fatalf("list due questions after migration: %v", err)
	}
	if len(due) != 2 {
		t.Fatalf("expected legacy and new due questions, got %d", len(due))
	}
}
