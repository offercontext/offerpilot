package mock

import (
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestTitleForSessionConfig(t *testing.T) {
	tests := []struct {
		name string
		cfg  SessionConfig
		want string
	}{
		{
			name: "explicit title wins",
			cfg:  SessionConfig{Title: "Frontend screen"},
			want: "Frontend screen",
		},
		{
			name: "company and role",
			cfg:  SessionConfig{Company: "ByteDance", Role: "Backend"},
			want: "ByteDance · Backend",
		},
		{
			name: "role only",
			cfg:  SessionConfig{Role: "Backend"},
			want: "Backend",
		},
		{
			name: "fallback title",
			cfg:  SessionConfig{},
			want: DefaultSessionTitle,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := TitleForSessionConfig(tt.cfg); got != tt.want {
				t.Fatalf("TitleForSessionConfig() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestBuildSessionDraftAppliesDefaults(t *testing.T) {
	appID := int64(7)
	kbID := int64(11)

	session := BuildSessionDraft(SessionDraftInput{
		ConversationID:  99,
		ApplicationID:   &appID,
		Title:           "ByteDance · Backend",
		Role:            "Backend",
		Company:         "ByteDance",
		KnowledgeBaseID: &kbID,
	})

	if session.ConversationID != 99 || session.ApplicationID == nil || *session.ApplicationID != appID {
		t.Fatalf("conversation/application binding wrong: %+v", session)
	}
	if session.Title != "ByteDance · Backend" || session.Role != "Backend" || session.Company != "ByteDance" {
		t.Fatalf("identity wrong: %+v", session)
	}
	if session.RoundType != "technical" {
		t.Fatalf("RoundType = %q, want technical", session.RoundType)
	}
	if session.Difficulty != "medium" {
		t.Fatalf("Difficulty = %q, want medium", session.Difficulty)
	}
	if session.QuestionCount != 5 {
		t.Fatalf("QuestionCount = %d, want 5", session.QuestionCount)
	}
	if session.QuestionSource != "mixed" {
		t.Fatalf("QuestionSource = %q, want mixed", session.QuestionSource)
	}
	if session.DurationMin != 0 || session.KnowledgeBaseID == nil || *session.KnowledgeBaseID != kbID {
		t.Fatalf("duration/knowledge base wrong: %+v", session)
	}
}

func TestBuildSessionDraftPreservesExplicitValues(t *testing.T) {
	session := BuildSessionDraft(SessionDraftInput{
		ConversationID: 77,
		Title:          "Custom",
		Role:           "Staff Engineer",
		RoundType:      "behavioral",
		Difficulty:     "hard",
		QuestionCount:  9,
		DurationMin:    45,
		QuestionSource: "bank",
	})

	if session.RoundType != "behavioral" || session.Difficulty != "hard" {
		t.Fatalf("explicit round/difficulty not preserved: %+v", session)
	}
	if session.QuestionCount != 9 || session.DurationMin != 45 || session.QuestionSource != "bank" {
		t.Fatalf("explicit numeric/source values not preserved: %+v", session)
	}
}

func TestBuildReviewNoteFillsApplicationIdentity(t *testing.T) {
	appID := int64(42)
	note := BuildReviewNote(ReviewNoteInput{
		Session: db.MockSession{
			ApplicationID: &appID,
			RoundType:     "technical",
		},
		Application: &db.Application{
			CompanyName:  "ByteDance",
			PositionName: "Backend",
		},
		Summary:    "Solid basics",
		Weaknesses: []string{"system design", "follow-up depth"},
		Today:      "2026-07-04",
	})

	if note.ApplicationID == nil || *note.ApplicationID != appID {
		t.Fatalf("ApplicationID = %v, want %d", note.ApplicationID, appID)
	}
	if note.Company != "ByteDance" || note.Position != "Backend" {
		t.Fatalf("identity = %q/%q, want ByteDance/Backend", note.Company, note.Position)
	}
	if note.Round != DefaultSessionTitle+"·technical" {
		t.Fatalf("Round = %q", note.Round)
	}
	if note.Date != "2026-07-04" || note.SelfReflection != "Solid basics" {
		t.Fatalf("note content wrong: %+v", note)
	}
	if note.DifficultyPoints != "待加强：system design；follow-up depth" {
		t.Fatalf("DifficultyPoints = %q", note.DifficultyPoints)
	}
}

func TestBuildReviewNoteSupportsUnboundSession(t *testing.T) {
	note := BuildReviewNote(ReviewNoteInput{
		Session: db.MockSession{RoundType: "hr"},
		Summary: "Needs practice",
		Today:   "2026-07-04",
	})

	if note.ApplicationID != nil {
		t.Fatalf("ApplicationID = %v, want nil", note.ApplicationID)
	}
	if note.Position != DefaultSessionTitle {
		t.Fatalf("Position = %q, want %q", note.Position, DefaultSessionTitle)
	}
	if note.Round != DefaultSessionTitle+"·hr" {
		t.Fatalf("Round = %q", note.Round)
	}
	if note.DifficultyPoints != "" {
		t.Fatalf("DifficultyPoints = %q, want empty", note.DifficultyPoints)
	}
}
