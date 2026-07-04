package chat

import (
	"encoding/json"
	"unicode/utf8"

	"github.com/offercontext/offerpilot/internal/ai"
	"github.com/offercontext/offerpilot/internal/db"
)

// ToAIMessages converts stored database messages into the model-facing shape.
func ToAIMessages(stored []db.ChatMessage, systemPrompt string) []ai.Message {
	out := []ai.Message{{Role: ai.RoleSystem, Content: systemPrompt}}
	for _, m := range stored {
		msg := ai.Message{Role: ai.Role(m.Role), Content: m.Content, ToolCallID: m.ToolCallID}
		if m.ToolCalls != "" {
			var tcs []ai.ToolCall
			if json.Unmarshal([]byte(m.ToolCalls), &tcs) == nil {
				msg.ToolCalls = tcs
			}
		}
		if m.ProviderBlocks != "" {
			var blocks []json.RawMessage
			if json.Unmarshal([]byte(m.ProviderBlocks), &blocks) == nil {
				msg.ProviderBlocks = blocks
			}
		}
		out = append(out, msg)
	}
	return out
}

func TitleFromMessage(msg string) string {
	const max = 20
	if utf8.RuneCountInString(msg) <= max {
		return msg
	}
	rs := []rune(msg)
	return string(rs[:max]) + "..."
}
