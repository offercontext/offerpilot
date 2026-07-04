package mock

import (
	"testing"

	"github.com/offercontext/offerpilot/internal/db"
)

func TestBuildTranscriptLabelsDialogueAndSkipsNonDialogue(t *testing.T) {
	transcript := BuildTranscript([]db.ChatMessage{
		{Role: "system", Content: "ignored setup"},
		{Role: "user", Content: "I built a cache"},
		{Role: "assistant", Content: "How did you handle invalidation?"},
		{Role: "tool", Content: `{"ok":true}`},
		{Role: "user", Content: ""},
		{Role: "user", Content: "With TTL and event updates"},
	})

	want := "候选人：ignored setup\n" +
		"候选人：I built a cache\n" +
		"面试官：How did you handle invalidation?\n" +
		"候选人：With TTL and event updates"
	if transcript != want {
		t.Fatalf("BuildTranscript() = %q, want %q", transcript, want)
	}
}

func TestBuildTranscriptReturnsEmptyForNoDialogue(t *testing.T) {
	transcript := BuildTranscript([]db.ChatMessage{
		{Role: "tool", Content: `{"ok":true}`},
		{Role: "user", Content: ""},
	})
	if transcript != "" {
		t.Fatalf("BuildTranscript() = %q, want empty", transcript)
	}
}
