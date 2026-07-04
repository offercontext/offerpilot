package chat

import (
	"strings"
	"testing"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

func promptTestDB(t *testing.T) *db.Database {
	t.Helper()
	d, err := db.Init(t.TempDir() + "/prompt.db")
	if err != nil {
		t.Fatalf("init db: %v", err)
	}
	t.Cleanup(func() { d.Close() })
	return d
}

func TestSystemPromptForFallsBackToGeneralPrompt(t *testing.T) {
	if got := SystemPromptFor(nil, nil); got != ai.ChatSystemPrompt {
		t.Fatalf("unexpected fallback prompt")
	}
}

func TestSystemPromptForNegoCoachIncludesOfferAndRelatedContext(t *testing.T) {
	d := promptTestDB(t)
	app := &db.Application{
		CompanyName:  "Acme",
		PositionName: "Backend Engineer",
		Status:       "offer",
		Source:       "test",
		Notes:        "application note for negotiation",
	}
	if err := d.CreateApplication(app); err != nil {
		t.Fatalf("create application: %v", err)
	}
	offer := &db.Offer{
		ApplicationID: &app.ID,
		CompanyName:   "Acme",
		PositionName:  "Backend Engineer",
		BaseMonthly:   30000,
		MonthsPerYear: 16,
	}
	if err := d.CreateOffer(offer); err != nil {
		t.Fatalf("create offer: %v", err)
	}
	if err := d.CreateInterviewNote(&db.InterviewNote{
		ApplicationID:    &app.ID,
		Company:          "Acme",
		Position:         "Backend Engineer",
		Round:            "system design",
		SelfReflection:   "strong architecture discussion",
		DifficultyPoints: "compensation framing",
	}); err != nil {
		t.Fatalf("create note: %v", err)
	}
	conv := &db.Conversation{Mode: "nego_coach", OfferID: &offer.ID}

	prompt := SystemPromptFor(d, conv)

	for _, want := range []string{"Acme", "Backend Engineer", "application note for negotiation", "strong architecture discussion", "compensation framing"} {
		if !strings.Contains(prompt, want) {
			t.Fatalf("prompt missing %q: %s", want, prompt)
		}
	}
}

func TestSystemPromptForMockInterviewUsesBoundSession(t *testing.T) {
	d := promptTestDB(t)
	conv, err := d.CreateConversationWithMode("mock", "mock_interview", nil)
	if err != nil {
		t.Fatalf("create conversation: %v", err)
	}
	if err := d.CreateMockSession(&db.MockSession{
		ConversationID:  conv.ID,
		Title:           "Backend mock",
		Role:            "Backend Engineer",
		Company:         "Acme",
		RoundType:       "technical",
		Difficulty:      "hard",
		QuestionCount:   3,
		QuestionSource:  "mixed",
		KnowledgeBaseID: nil,
	}); err != nil {
		t.Fatalf("create mock session: %v", err)
	}

	prompt := SystemPromptFor(d, conv)

	for _, want := range []string{"Backend Engineer", "Acme", "technical", "hard"} {
		if !strings.Contains(prompt, want) {
			t.Fatalf("mock prompt missing %q: %s", want, prompt)
		}
	}
}

func TestSystemPromptForMockInterviewFallsBackWhenSessionMissing(t *testing.T) {
	d := promptTestDB(t)
	conv := &db.Conversation{ID: 999, Mode: "mock_interview"}

	if got := SystemPromptFor(d, conv); got != ai.MockInterviewerPromptFallback {
		t.Fatalf("unexpected missing-session fallback")
	}
}
