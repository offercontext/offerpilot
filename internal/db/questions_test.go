package db

import (
	"testing"
	"time"
)

func TestQuestionCRUDAndBulk(t *testing.T) {
	d := newTestDB(t)

	q := &Question{Category: "Go并发", Difficulty: "medium", Question: "什么是 goroutine 泄漏？", ReferenceAnswer: "阻塞未退出的 goroutine", Tags: []string{"go", "并发"}, SourceType: "manual"}
	if err := d.CreateQuestion(q); err != nil {
		t.Fatalf("create question: %v", err)
	}
	if q.ID == 0 {
		t.Fatal("expected non-zero id")
	}
	if q.Status != QuestionStatusNew {
		t.Fatalf("expected default status new, got %q", q.Status)
	}

	got, err := d.GetQuestion(q.ID)
	if err != nil {
		t.Fatalf("get question: %v", err)
	}
	if len(got.Tags) != 2 || got.Tags[0] != "go" {
		t.Fatalf("tags round-trip failed: %+v", got.Tags)
	}

	got.Difficulty = "hard"
	got.Question = "更新后的题目"
	if err := d.UpdateQuestion(got); err != nil {
		t.Fatalf("update question: %v", err)
	}
	reloaded, err := d.GetQuestion(got.ID)
	if err != nil {
		t.Fatalf("reload: %v", err)
	}
	if reloaded.Difficulty != "hard" || reloaded.Question != "更新后的题目" {
		t.Fatalf("update not persisted: %+v", reloaded)
	}

	// Bulk insert.
	batch := []*Question{
		{Question: "题目A", Difficulty: "easy", SourceType: "ai_knowledge"},
		{Question: "题目B", Difficulty: "hard", SourceType: "ai_knowledge"},
	}
	if err := d.BulkCreateQuestions(batch); err != nil {
		t.Fatalf("bulk create: %v", err)
	}
	if batch[0].ID == 0 || batch[1].ID == 0 {
		t.Fatal("bulk create did not populate ids")
	}

	all, err := d.ListQuestions(QuestionFilter{})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("expected 3 questions, got %d", len(all))
	}

	hard, err := d.ListQuestions(QuestionFilter{Difficulty: "hard"})
	if err != nil {
		t.Fatalf("list hard: %v", err)
	}
	if len(hard) != 2 {
		t.Fatalf("expected 2 hard questions, got %d", len(hard))
	}

	if err := d.DeleteQuestion(q.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if _, err := d.GetQuestion(q.ID); err == nil {
		t.Fatal("expected error getting deleted question")
	}
}

func TestAddQuestionReviewUpdatesState(t *testing.T) {
	d := newTestDB(t)
	q := &Question{Question: "测试题", Difficulty: "medium", SourceType: "manual"}
	if err := d.CreateQuestion(q); err != nil {
		t.Fatalf("create: %v", err)
	}

	// Rating "hard" (2) → practicing, next review ~3 days out.
	updated, err := d.AddQuestionReview(&QuestionReview{QuestionID: q.ID, Rating: QuestionRatingHard, Note: "有点模糊"})
	if err != nil {
		t.Fatalf("add review: %v", err)
	}
	if updated.Status != QuestionStatusPracticing {
		t.Fatalf("expected practicing, got %q", updated.Status)
	}
	if updated.PracticeCount != 1 {
		t.Fatalf("expected practice_count 1, got %d", updated.PracticeCount)
	}
	if updated.LastPracticedAt == nil || updated.NextReviewAt == nil {
		t.Fatal("expected last/next review timestamps set")
	}
	if !updated.NextReviewAt.After(time.Now().Add(2 * 24 * time.Hour)) {
		t.Fatalf("expected next review ~3 days out, got %v", updated.NextReviewAt)
	}

	// Rating "good" (3) → mastered.
	updated, err = d.AddQuestionReview(&QuestionReview{QuestionID: q.ID, Rating: QuestionRatingGood})
	if err != nil {
		t.Fatalf("add review 2: %v", err)
	}
	if updated.Status != QuestionStatusMastered {
		t.Fatalf("expected mastered, got %q", updated.Status)
	}
	if updated.PracticeCount != 2 {
		t.Fatalf("expected practice_count 2, got %d", updated.PracticeCount)
	}
}

func TestPracticeStats(t *testing.T) {
	d := newTestDB(t)
	for i := 0; i < 3; i++ {
		q := &Question{Question: "题", Difficulty: "medium", SourceType: "manual"}
		if err := d.CreateQuestion(q); err != nil {
			t.Fatalf("create: %v", err)
		}
		if i == 0 {
			if _, err := d.AddQuestionReview(&QuestionReview{QuestionID: q.ID, Rating: QuestionRatingGood}); err != nil {
				t.Fatalf("review: %v", err)
			}
		}
	}

	stats, err := d.PracticeStats()
	if err != nil {
		t.Fatalf("stats: %v", err)
	}
	if stats.Total != 3 {
		t.Fatalf("expected total 3, got %d", stats.Total)
	}
	if stats.Mastered != 1 {
		t.Fatalf("expected mastered 1, got %d", stats.Mastered)
	}
	if stats.New != 2 {
		t.Fatalf("expected new 2, got %d", stats.New)
	}
	if stats.TodayReviews != 1 {
		t.Fatalf("expected today_reviews 1, got %d", stats.TodayReviews)
	}
	if stats.StreakDays != 1 {
		t.Fatalf("expected streak 1, got %d", stats.StreakDays)
	}
	// The two never-reviewed questions are due; the mastered one is scheduled 7 days out.
	if stats.Due != 2 {
		t.Fatalf("expected due 2, got %d", stats.Due)
	}
}

func TestListDueQuestions(t *testing.T) {
	d := newTestDB(t)
	q1 := &Question{Question: "新题", Difficulty: "medium", SourceType: "manual"}
	q2 := &Question{Question: "已掌握", Difficulty: "medium", SourceType: "manual"}
	if err := d.CreateQuestion(q1); err != nil {
		t.Fatalf("create q1: %v", err)
	}
	if err := d.CreateQuestion(q2); err != nil {
		t.Fatalf("create q2: %v", err)
	}
	if _, err := d.AddQuestionReview(&QuestionReview{QuestionID: q2.ID, Rating: QuestionRatingGood}); err != nil {
		t.Fatalf("review q2: %v", err)
	}

	due, err := d.ListDueQuestions(10)
	if err != nil {
		t.Fatalf("due: %v", err)
	}
	// Only the never-reviewed q1 is due; q2 is scheduled a week out.
	if len(due) != 1 || due[0].ID != q1.ID {
		t.Fatalf("expected only q1 due, got %+v", due)
	}
}
