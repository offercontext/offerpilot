package chat

import (
	"encoding/json"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

type MessageStore interface {
	AppendMessage(m *db.ChatMessage) error
}

func PersistAdded(store MessageStore, convID int64, added []ai.Message) error {
	for _, m := range added {
		cm := &db.ChatMessage{ConversationID: convID, Role: string(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if len(m.ToolCalls) > 0 {
			b, _ := json.Marshal(m.ToolCalls)
			cm.ToolCalls = string(b)
		}
		if len(m.ProviderBlocks) > 0 {
			b, _ := json.Marshal(m.ProviderBlocks)
			cm.ProviderBlocks = string(b)
		}
		if err := store.AppendMessage(cm); err != nil {
			return err
		}
	}
	return nil
}
