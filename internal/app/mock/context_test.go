package mock

import (
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

type fakeContextStore struct {
	questions []db.Question
	knowledge []db.KnowledgeSearchResult
	notes     []db.InterviewNote

	questionCalls int
	searchCalls   int
	notesCalls    int

	questionFilter db.QuestionFilter
	searchFilter   db.KnowledgeSearchFilter
	notesAppID     int64
}

func (s *fakeContextStore) ListQuestions(filter db.QuestionFilter) ([]db.Question, error) {
	s.questionCalls++
	s.questionFilter = filter
	return s.questions, nil
}

func (s *fakeContextStore) SearchKnowledge(filter db.KnowledgeSearchFilter) ([]db.KnowledgeSearchResult, error) {
	s.searchCalls++
	s.searchFilter = filter
	return s.knowledge, nil
}

func (s *fakeContextStore) ListInterviewNotes(appID int64) ([]db.InterviewNote, error) {
	s.notesCalls++
	s.notesAppID = appID
	return s.notes, nil
}

func TestBuildContextAssemblesMixedSourceContext(t *testing.T) {
	kbID := int64(3)
	appID := int64(4)
	store := &fakeContextStore{
		knowledge: []db.KnowledgeSearchResult{
			{Snippet: "cache invalidation notes"},
			{Snippet: "rate limiting notes"},
		},
		notes: []db.InterviewNote{
			{DifficultyPoints: "system design depth"},
			{DifficultyPoints: ""},
			{DifficultyPoints: "follow-up clarity"},
			{DifficultyPoints: "complexity analysis"},
			{DifficultyPoints: "tradeoff framing"},
			{DifficultyPoints: "testing strategy"},
			{DifficultyPoints: "ownership story"},
			{DifficultyPoints: "extra should be capped"},
		},
	}
	for i := 0; i < 13; i++ {
		store.questions = append(store.questions, db.Question{ID: int64(i + 1), Question: "question"})
	}

	ctx := BuildContext(store, &db.MockSession{
		ApplicationID:   &appID,
		Difficulty:      "hard",
		KnowledgeBaseID: &kbID,
		QuestionSource:  "mixed",
	})

	if store.questionCalls != 1 || store.questionFilter.Difficulty != "hard" || store.questionFilter.KnowledgeBaseID != kbID {
		t.Fatalf("question lookup wrong: calls=%d filter=%+v", store.questionCalls, store.questionFilter)
	}
	if len(ctx.PickedQuestions) != 12 {
		t.Fatalf("PickedQuestions len = %d, want 12", len(ctx.PickedQuestions))
	}
	if store.searchCalls != 1 || store.searchFilter.KnowledgeBaseID != kbID || store.searchFilter.Limit != 6 {
		t.Fatalf("knowledge lookup wrong: calls=%d filter=%+v", store.searchCalls, store.searchFilter)
	}
	if len(ctx.KnowledgeChunks) != 2 || ctx.KnowledgeChunks[0] != "cache invalidation notes" {
		t.Fatalf("KnowledgeChunks wrong: %+v", ctx.KnowledgeChunks)
	}
	if store.notesCalls != 1 || store.notesAppID != appID {
		t.Fatalf("notes lookup wrong: calls=%d appID=%d", store.notesCalls, store.notesAppID)
	}
	if len(ctx.WeakPoints) != 6 {
		t.Fatalf("WeakPoints len = %d, want 6: %+v", len(ctx.WeakPoints), ctx.WeakPoints)
	}
	if ctx.WeakPoints[0] != "system design depth" || ctx.WeakPoints[5] != "ownership story" {
		t.Fatalf("WeakPoints wrong: %+v", ctx.WeakPoints)
	}
}

func TestBuildContextRespectsQuestionSource(t *testing.T) {
	kbID := int64(9)
	store := &fakeContextStore{}

	_ = BuildContext(store, &db.MockSession{QuestionSource: "bank"})
	if store.questionCalls != 1 || store.searchCalls != 0 {
		t.Fatalf("bank source calls question/search = %d/%d, want 1/0", store.questionCalls, store.searchCalls)
	}

	store = &fakeContextStore{}
	_ = BuildContext(store, &db.MockSession{QuestionSource: "knowledge", KnowledgeBaseID: &kbID})
	if store.questionCalls != 0 || store.searchCalls != 1 {
		t.Fatalf("knowledge source calls question/search = %d/%d, want 0/1", store.questionCalls, store.searchCalls)
	}
}
