package chat

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

type recordingMessageStore struct {
	messages []db.ChatMessage
	errAt    int
}

func (s *recordingMessageStore) AppendMessage(m *db.ChatMessage) error {
	if s.errAt > 0 && len(s.messages)+1 == s.errAt {
		return errors.New("append failed")
	}
	s.messages = append(s.messages, *m)
	return nil
}

func TestPersistAddedSerializesModelMetadata(t *testing.T) {
	store := &recordingMessageStore{}
	added := []ai.Message{
		{
			Role:    ai.RoleAssistant,
			Content: "checking",
			ToolCalls: []ai.ToolCall{
				{ID: "call-1", Name: "list_applications", Args: json.RawMessage(`{"status":"offer"}`)},
			},
			ProviderBlocks: []json.RawMessage{
				json.RawMessage(`{"type":"thinking","signature":"sig"}`),
			},
		},
		{
			Role:       ai.RoleTool,
			Content:    `[]`,
			ToolCallID: "call-1",
		},
	}

	if err := PersistAdded(store, 42, added); err != nil {
		t.Fatalf("persist added: %v", err)
	}

	if len(store.messages) != 2 {
		t.Fatalf("expected 2 messages, got %d", len(store.messages))
	}
	first := store.messages[0]
	if first.ConversationID != 42 || first.Role != "assistant" || first.Content != "checking" {
		t.Fatalf("unexpected assistant message: %+v", first)
	}
	if first.ToolCalls != `[{"id":"call-1","name":"list_applications","args":{"status":"offer"}}]` {
		t.Fatalf("unexpected tool calls: %s", first.ToolCalls)
	}
	if first.ProviderBlocks != `[{"type":"thinking","signature":"sig"}]` {
		t.Fatalf("unexpected provider blocks: %s", first.ProviderBlocks)
	}
	second := store.messages[1]
	if second.Role != "tool" || second.ToolCallID != "call-1" || second.Content != `[]` {
		t.Fatalf("unexpected tool message: %+v", second)
	}
}

func TestPersistAddedStopsOnAppendError(t *testing.T) {
	store := &recordingMessageStore{errAt: 2}

	err := PersistAdded(store, 42, []ai.Message{
		{Role: ai.RoleAssistant, Content: "first"},
		{Role: ai.RoleAssistant, Content: "second"},
	})

	if err == nil {
		t.Fatal("expected append error")
	}
	if len(store.messages) != 1 {
		t.Fatalf("expected only first message persisted, got %d", len(store.messages))
	}
}
