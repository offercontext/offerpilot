package db

import "testing"

func TestMockSessionCRUD(t *testing.T) {
	d := newTestDB(t)

	// A mock session is bound to a conversation created with mode='mock_interview'.
	conv, err := d.CreateConversationWithMode("后端·字节 模拟面试", "mock_interview", nil)
	if err != nil {
		t.Fatalf("create conversation: %v", err)
	}

	s := &MockSession{
		ConversationID: conv.ID,
		Title:          "后端·字节 模拟面试",
		Role:           "后端开发",
		Company:        "字节跳动",
		RoundType:      "technical",
		Difficulty:     "medium",
		QuestionCount:  5,
		DurationMin:    30,
		QuestionSource: "mixed",
	}
	if err := d.CreateMockSession(s); err != nil {
		t.Fatalf("create session: %v", err)
	}
	if s.ID == 0 {
		t.Fatal("expected non-zero session id")
	}
	if s.Status != "in_progress" {
		t.Fatalf("expected default status in_progress, got %q", s.Status)
	}
	if s.QuestionIndex != 0 {
		t.Fatalf("expected question_index 0, got %d", s.QuestionIndex)
	}

	got, err := d.GetMockSession(s.ID)
	if err != nil {
		t.Fatalf("get session: %v", err)
	}
	if got.Role != "后端开发" || got.Difficulty != "medium" || got.ConversationID != conv.ID {
		t.Fatalf("unexpected session: %+v", got)
	}

	byConv, err := d.GetMockSessionByConversation(conv.ID)
	if err != nil {
		t.Fatalf("get by conversation: %v", err)
	}
	if byConv.ID != s.ID {
		t.Fatalf("by-conversation lookup mismatch: want %d got %d", s.ID, byConv.ID)
	}

	if err := d.UpdateMockSessionProgress(s.ID, 3); err != nil {
		t.Fatalf("update progress: %v", err)
	}
	reloaded, _ := d.GetMockSession(s.ID)
	if reloaded.QuestionIndex != 3 {
		t.Fatalf("expected question_index 3, got %d", reloaded.QuestionIndex)
	}
}

func TestMockSessionFinishAndScores(t *testing.T) {
	d := newTestDB(t)
	conv, _ := d.CreateConversationWithMode("模拟", "mock_interview", nil)
	s := &MockSession{ConversationID: conv.ID, Title: "t", Role: "前端", Difficulty: "hard", QuestionCount: 4}
	if err := d.CreateMockSession(s); err != nil {
		t.Fatalf("create: %v", err)
	}

	feedback := `{"summary":"中等","strengths":["STAR"],"weaknesses":["系统设计"]}`
	scores := MockScores{ScoreOverall: 78, ScoreCommunication: 80, ScoreDepth: 72, ScoreStructure: 75, ScoreConfidence: 85}
	if err := d.FinishMockSession(s.ID, scores, feedback); err != nil {
		t.Fatalf("finish: %v", err)
	}
	done, _ := d.GetMockSession(s.ID)
	if done.Status != "completed" {
		t.Fatalf("expected completed, got %q", done.Status)
	}
	if done.EndedAt == nil {
		t.Fatal("expected ended_at set")
	}
	if done.ScoreOverall == nil || *done.ScoreOverall != 78 {
		t.Fatalf("expected score_overall 78, got %+v", done.ScoreOverall)
	}
	if *done.ScoreConfidence != 85 {
		t.Fatalf("expected score_confidence 85, got %d", *done.ScoreConfidence)
	}
	if done.Feedback != feedback {
		t.Fatalf("feedback not persisted, got %q", done.Feedback)
	}
}

func TestMockSessionListByStatus(t *testing.T) {
	d := newTestDB(t)
	c1, _ := d.CreateConversationWithMode("a", "mock_interview", nil)
	c2, _ := d.CreateConversationWithMode("b", "mock_interview", nil)
	if err := d.CreateMockSession(&MockSession{ConversationID: c1.ID, Title: "s1"}); err != nil {
		t.Fatal(err)
	}
	if err := d.CreateMockSession(&MockSession{ConversationID: c2.ID, Title: "s2"}); err != nil {
		t.Fatal(err)
	}
	if err := d.FinishMockSession(2, MockScores{ScoreOverall: 60}, "{}"); err != nil {
		t.Fatal(err)
	}

	all, err := d.ListMockSessions("")
	if err != nil {
		t.Fatalf("list all: %v", err)
	}
	if len(all) != 2 {
		t.Fatalf("want 2 sessions, got %d", len(all))
	}

	progress, _ := d.ListMockSessions("in_progress")
	if len(progress) != 1 || progress[0].Title != "s1" {
		t.Fatalf("want 1 in_progress s1, got %+v", progress)
	}
	completed, _ := d.ListMockSessions("completed")
	if len(completed) != 1 || completed[0].Title != "s2" {
		t.Fatalf("want 1 completed s2, got %+v", completed)
	}
}

func TestMockSessionDeleteAndCascade(t *testing.T) {
	d := newTestDB(t)
	conv, _ := d.CreateConversationWithMode("c", "mock_interview", nil)
	s := &MockSession{ConversationID: conv.ID, Title: "x"}
	if err := d.CreateMockSession(s); err != nil {
		t.Fatal(err)
	}
	// Deleting the conversation cascades to the session (FK ON DELETE CASCADE).
	if err := d.DeleteConversation(conv.ID); err != nil {
		t.Fatalf("delete conversation: %v", err)
	}
	if _, err := d.GetMockSession(s.ID); err == nil {
		t.Fatal("expected session gone after conversation cascade delete")
	}
}